"""
This file define the main holon classes
BaseHolon implement the minim methods necessary for communication with other holons
LightHolons adds helper methods to handle message, topics and events
Holon adds a main thread to LightHolon
"""



from threading import Thread, Lock
from copy import copy
from time import sleep, time
import uuid
import logging

import Ice 


from icehms import hms




class _BaseHolon(object):
    """
    Base holon only implementing registration to ice
    and some default methods called by AgentManager
    """
    def __init__(self, name=None, hmstype=None):
        if not name:
            name = self.__class__.__name__ + "_" + str(uuid.uuid1())
        self.name = name
        self._logger = logging.getLogger(self.__class__.__name__ + "::" + self.name)
        if len(logging.root.handlers) == 0: #dirty hack
            logging.basicConfig()
        self._icemgr = None
        self.registeredToGrid = False
        self._agentMgr = None
        self.proxy = None
        if not hmstype:
            hmstype = self.ice_id()
        self.hmstype = hmstype

    def getName(self, ctx=None): 
        return self.name

    def setAgentManager(self, mgr): 
        """
        Set agent manager object for a holon. keeping a pointer enable us create other holons 
        also keep a pointer to icemgr
        """
        self._agentMgr = mgr
        self._icemgr = mgr.icemgr

    def cleanup(self):
        """
        Call by agent manager when deregistering
        """

    def start(self, current=None):
        """ 
        Call by Agent manager after registering
        """
        self._logger.info("Starting" )
                
    def stop(self, current=None):
        """ 
        Call by agent manager before deregistering
        """
        self._logger.info("stop called ")


    def shutdown(self, ctx=None):
        """
        shutdown a holon, deregister from icegrid and icestorm and call stop() and cleanup on holon instances
        I read somewhere this should notbe available in a MAS, holons should only shutdown themselves
        """
        try:
            self._agentMgr.removeAgent(self)
        except Ice.Exception, why:
            self._logger.warn(why)

    def getClassName(self, ctx=None):
        return self.__class__.__name__

    def __str__(self):
        return "[Holon: %s] " % (self.name)

    def __repr__(self):
        return self.__str__()




class _LightHolon(_BaseHolon):
    """Base Class for non active Holons or holons setting up their own threads
    implements helper methods like to handle topics, messages and events 
    """
    def __init__(self, name=None, hmstype=None):
        _BaseHolon.__init__(self, name, hmstype)
        self._publishedTopics = {} 
        self._subscribedTopics = {}
        self.mailbox = MessageQueue()


    def _subscribeEvent(self, topicName):
        self._subscribeTopic(topicName, server=self._icemgr.eventMgr)

    def _subscribeTopic(self, topicName, server=None):
        """
        subscribe ourself to a topic using safest ice tramsmition protocol
        The holon needs to inherit the topic proxy and implemented the topic methods
        """
        topic = self._icemgr.subscribeTopic(topicName, self.proxy.ice_twoway(), server=server)
        self._subscribedTopics[topicName] = topic
        return topic

    def _subscribeTopicUDP(self, topicName):
        """
        subscribe ourself to a topic, using UDP
        The holon needs to inherit the topic proxy and implemented the topic methods
        """
        topic = self._icemgr.subscribeTopic(topicName, self.proxy.ice_datagram())
        self._subscribedTopics[topicName] = topic
        return topic


    def _getPublisher(self, topicName, prxobj, permanentTopic=True, server=None):
        """
        get a publisher object for a topic
        create it if it does not exist
        prxobj is the ice interface obj for the desired topic. This is necessary since topics have an interface
        if permanentTopic is False then we destroy it when we leave
        otherwise it stays
        if server is None then default server is used
        """
        pub = self._icemgr.getPublisher(topicName, prxobj, server=server)
        self._publishedTopics[topicName] = (server, permanentTopic)
        return  pub

    def _getEventPublisher(self, topicName):
        """
        Wrapper over getPublisher, for generic event interface
        """
        return self._getPublisher(topicName, hms.GenericEventInterfacePrx, permanentTopic=True, server=self._icemgr.eventMgr)

    def newEvent(self, name, arguments, icebytes):
        """
        Received event from GenericEventInterface
        """
        self._logger.warn("Holon registered to topic, but newEvent method not overwritten")


    def _unsubscribeTopic(self, name):
        """
        As the name says. It is necessary to unsubscribe to topics before exiting to avoid exceptions
        and being able to re-subscribe without error next time
        """
        self._subscribedTopics[name].unsubscribe(self.proxy)
        del(self._subscribedTopics[name])

    def cleanup(self):
        """
        Remove stuff from the database
        not catching exceptions since it is not very important
        """
        for topic in self._subscribedTopics.keys():
            self._unsubscribeTopic(topic)

        for k, v in self._publishedTopics.items():
            if not v[1]:
                topic = self._icemgr.getTopic(k, server=v[0], create=False)
                if topic:
                    #topic.destroy()
                    self._logger.info("Topic destroying disabled since it can confuse clients")

    def getPublishedTopics(self, current):
        """
        Return a list of all topics published by one agent
        """
        return self._publishedTopics.keys()

    def printMsgQueue(self, ctx=None):
        for msg in self.mailbox.copy():
            print "%s" % msg.creationTime + ' receiving ' + msg.body

    
    def putMessage(self, msg, current=None):
        #is going to be called by other process/or threads so must be protected
        self._logger.debug("Received message: " + msg.body)
        self.mailbox.append(msg)

class _Holon(_LightHolon, Thread):
    """
    Holon is the same as LightHolon but starts a thread automatically
    """
    def __init__(self, name=None, hmstype=None):
        Thread.__init__(self)
        _LightHolon.__init__(self, name, hmstype)
        self._stop = False
        self._lock = Lock()

    def start(self):
        """
        Re-implement because start exist in LightHolon
        """
        Thread.start(self)

    def stop(self, current=None):
        """
        Attempt to stop processing thread
        """
        self._logger.info("stop called ")
        self._stop = True

    def _getProxyBlocking(self, address):
        return self._getHolonBlocking(address)

    def _getHolonBlocking(self, address):
        """
        Attempt to connect a given holon ID
        block until we connect
        return none if interrupted by self._stop
        """
        self._logger.info( "Trying to connect  to " + address)
        prx = None    
        while not prx:
            prx = self._icemgr.getProxy(address)
            sleep(0.1)
            if self._stop:
                return None
        self._logger.info( "Got connection to %s", address)
        return prx

    def run(self):
        """ To be implemented by active holons
        """
        pass



class BaseHolon(hms.Holon, _BaseHolon):
    def __init__(self, *args, **kw):
        _BaseHolon.__init__(self, args, **kw)

class LightHolon(hms.Holon, hms.GenericEventInterface, _LightHolon):
    def __init__(self, *args, **kw):
        _LightHolon.__init__(self, *args, **kw)

class Holon(hms.Holon, hms.GenericEventInterface, _Holon):
    def __init__(self, *args, **kw):
        _Holon.__init__(self, *args, **kw)


class Agent(hms.Agent, hms.Holon, _Holon):
    """
    Legacy
    """
    def __init__(self, *args, **kw):
        _Holon.__init__(self, *args, **kw)

class Message(hms.Message):
    """
    Wrapper over the Ice Message definition, 
    """
    def __init__(self, *args, **kwargs):
        hms.Message.__init__(self, *args, **kwargs)
        self.createTime = time()

    def __setattr__(self, name, val):
        #format everything to string
        if name == "parameters" and val:
            val = [str(i) for i in val]
        elif name == "arguments" and val:
            #val = {k:str(v) for k,v in val.items()} # does not work with python < 2.6
            d = dict()
            for k, v in val.items():
                if v in ("None", None): 
                    v = ""
                d[k] = str(v)
            val = d
        return hms.Message.__setattr__(self, name, val)



class MessageQueue(object):
    def __init__(self):
        self.lock = Lock()
        self._list = []
        
    def append(self, msg):
        self.lock.acquire()    
        self._list.append(msg)
        self.lock.release()

    def remove(self, msg):
        self.lock.acquire()
        #print "LIST", self._list
        #print msg
        self._list.remove(msg)
        self.lock.release()


    def pop(self):
        self.lock.acquire()
        if len(self._list) > 0:
            msg = self._list.pop(0)
        else: 
            msg = None
        self.lock.release()
        return msg

    def copy(self):
        """ return a copy of the current mailbox
        usefull for, for example, iteration
        """
        self.lock.acquire()
        #copy =  deepcopy(self._list)
        #shallow copy should be enough since as long as we have 
        # a link to the message python gc should not delete it
        # and as long as we do not modify message in our mailbox
        listcopy =  copy(self._list) 
        self.lock.release()
        return listcopy

    def __getitem__(self, x):
        """ to support mailbox[idx]"""
        return self._list.__getitem__(x)
    
    def __repr__(self):
        """ what is printed when printing the maibox  """
        return self._list.__repr__()




