using System;
using System.Net;
using System.Net.Sockets;
using System.Collections.Generic;
//using hms; cleaner to says hms everytime
/*
 * IceHMS is small wrapper around ice to setup a multi-agent like system
*/

namespace icehms
{
    public class Holon: hms.HolonDisp_
    {
        public string Name;
        public Ice.ObjectPrx Proxy;

        public Holon(string name)
        {
            Name = name;
        }

        public override string getName(Ice.Current current)
        {
            return Name;
        }

        public override void putMessage(hms.Message message, Ice.Current current)
        {
            log("We got a new message: " + message);
        }

        public void log(string message)
        {
            Console.WriteLine("IceHMS: " + Name + ": " + message);
        }
    }


    public class IceApp
    {
        /*
        * IceApp faciliate communication with other agents in icehms network
        * Initialize Ice, offer links to necessary objects, offer methods for common actions
        * One class per process
        * It can be shared between threads. Class is thread safe
        */
        IceGrid.QueryPrx Query;
        IceStorm.TopicManagerPrx EventMgr;
        Ice.Communicator Communicator;
        string IceGridHost;
        int IceGridPort;
        IceGrid.AdminPrx _Admin;
        IceGrid.AdminSessionPrx _Session;
        IceGrid.RegistryPrx _Registry;
        Ice.ObjectAdapter _Adapter;


       public IceApp(string host, int port)
       {
           IceGridHost = host;
           IceGridPort = port;
            log("My IPAddress is: " + findLocalIPAddress());
           //initialize Ice
           Ice.Properties prop = Ice.Util.createProperties();
           prop.setProperty("hms.AdapterId", "VC2ICE");
           prop.setProperty("hms.Endpoints", "tcp -h " + IceGridHost +":udp -h " + IceGridHost);
           prop.setProperty("Ice.Default.Locator", "IceGrid/Locator:tcp -p " + IceGridPort + " -h " + IceGridHost);
           prop.setProperty("Ice.ThreadPool.Server.Size", "5");
           prop.setProperty("Ice.ThreadPool.Server.SizeMax", "100000");
           prop.setProperty("Ice.ThreadPool.Client.Size", "5");
           prop.setProperty("Ice.ThreadPool.Client.SizeMax", "100000");

           Ice.InitializationData iceidata = new Ice.InitializationData();
           iceidata.properties = prop;
           Communicator = Ice.Util.initialize(iceidata); // could add sys.argv
           _Adapter = Communicator.createObjectAdapter("hms");
           _Adapter.activate(); 
           //Now are we ready to communicate with others
           //getting usefull proxies

           try
           {
               // proxy to icegrid to register our vc devices
               Query = IceGrid.QueryPrxHelper.checkedCast(Communicator.stringToProxy("IceGrid/Query"));
               if (Query == null)
               {
                   log("invalid ICeGrid proxy");
               }
               // proxy to icestorm to publish events
               EventMgr = IceStorm.TopicManagerPrxHelper.checkedCast(Communicator.stringToProxy("EventServer/TopicManager"));
               if (EventMgr == null)
               {
                   log("invalid IceStorm proxy");
               }
               //these 2 objects are only needed to get the IceGrid admin object in order to register
               _Registry = IceGrid.RegistryPrxHelper.uncheckedCast(Communicator.stringToProxy("IceGrid/Registry"));
               _Session = _Registry.createAdminSession("foo", "bar"); //authentication is disable so whatever works

           }
           catch (Ice.NotRegisteredException)
           {
               log("If we fail here it is probably because the Icebox objects are not registered");
           }
           catch (Exception e)
           {
               log("IceGrid Server not found!!!!!: " + e);
           }

        //properties set, now initialize Ice and get comm


       }

       private string findLocalIPAddress()
       {
           // machines can have many interfaces, there is no way to be sure we will return the correct interface
           // but by opening a socket to IceGrid we know that, at least, 
           // we use an IP address that can communicate to IceGrid
            UdpClient udpClient = new UdpClient(0);
            try
            {
                udpClient.Connect(IceGridHost, 0);
            }
            catch (Exception e) 
            {
                // If we get here we have network problem, so returning something is probably stupide
                log("Error determining IP address, returning 127.0.0.1: " + e);
                return "127.0.0.1";
            }
            System.Net.IPAddress address = ((System.Net.IPEndPoint)udpClient.Client.LocalEndPoint).Address;
            string test = address.ToString();
            return IPAddress.Parse(test).ToString() ;
       }

       public void cleanup()
       {
           //alway call this, Ice needs to be closed cleanly
           if (Communicator != null)
           {
               Communicator.destroy();
           }
       }

       private IceGrid.AdminPrx getIceGridAdmin()
       {
            // the session goes in timeout so check it
            try
            {
                _Session.ice_ping();
            }
            catch (Ice.Exception) //Session and admin objects have timeouts, maybe they should be closed after used
            {
                _Session = _Registry.createAdminSession("foo", "bar"); //authentication is disable so whatever works
                _Admin = _Session.getAdmin();
            }
            return _Admin;
      }

       public void register(Holon holon)
       {
            // register an object to local Ice adapter and yellowpage service (IceGrid)
            Ice.Identity iceid = Communicator.stringToIdentity(holon.Name);
            Ice.ObjectPrx proxy = _Adapter.add((Ice.Object)holon, iceid);
            holon.Proxy = proxy;

           // It is very important to deregister objects before closing!!
           // Otherwise ghost links are created
           IceGrid.AdminPrx admin = getIceGridAdmin();
           try
           {
               admin.addObjectWithType(holon.Proxy, holon.ice_id());
           }
           catch (IceGrid.ObjectExistsException)
           {
               admin.updateObject(holon.Proxy);
           }
       }

       public void deregister(Holon holon)
       {
            //remove from IceGrid and from local adapter
            Ice.Identity iceid = holon.Proxy.ice_getIdentity();
            IceGrid.AdminPrx admin = getIceGridAdmin();
            try
            {
                admin.removeObject(iceid);
            }
            catch (Exception ex)
            {
                log("Could not deregister holon from IceGrid: " + ex);
            }
            _Adapter.remove(iceid);
       }

       public void log(string message)
       {
           Console.WriteLine("IceHMS: " + message);
       }

        public void subscribeEvent(Holon holon, string topicName)
        {
            IceStorm.TopicPrx topic = getTopic(topicName);
        Dictionary<string, string> qos = new Dictionary<string, string>();
        qos["reliability"] = ""; //#"" and "ordered" are the only possibilities see doc
        qos["retryCount"] = "-1"; // #-1 means to never remove a dead subscriber from list 
        try
        {
            topic.subscribeAndGetPublisher(qos, holon.Proxy);
        }
        catch (IceStorm.AlreadySubscribed)
        {
            log( "Allready subscribed to topic, that is ok" );
        }
        log(holon.Proxy + " subscribed to " + topicName );
        }

        public IceStorm.TopicPrx getTopic(string topicName)
        {
           // Retrieve the topic
           IceStorm.TopicPrx topic;
           try
           {
               topic = EventMgr.retrieve(topicName);
           }
           catch (IceStorm.NoSuchTopic)
           {
               try
               {
                   topic = EventMgr.create(topicName);
               }
               catch (IceStorm.TopicExists)
               {
                   //maybe someone has created it inbetween so try again, otherwise raise exception
                   topic = EventMgr.retrieve(topicName);
               }
           }
           return topic;

        }

       public hms.GenericEventInterfacePrx getEventPublisher(string topicName)
       {
           // Get the topic's publisher object, using towways
           IceStorm.TopicPrx topic = getTopic(topicName);
           Ice.ObjectPrx publisher = topic.getPublisher();
           return hms.GenericEventInterfacePrxHelper.uncheckedCast(publisher);
       }

       public Ice.ObjectPrx[] findHolon(string type) //wraper arond findAllObjectByType for consistency with python icehms
       {
           return Query.findAllObjectsByType(type);
       }
   }
}