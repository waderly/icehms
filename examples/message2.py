from time import sleep
import sys
sys.path.append("..")
from icehms import startHolonStandalone, Holon

class Client(Holon):
    def run(self):
        while not self._stop:
            msg = self.mailbox.pop()
            if msg:
                print "got message:", msg
            sleep(1)

    def putMessage(self, msg, ctx=None):
        print "call"
        sleep(3)
        return "KK"

if __name__ == "__main__":
    holon = Client("Holon2")
    holon.setLogLevel(10)
    holon.other = ("Holon1")
    startHolonStandalone(holon, logLevel=10)
 


