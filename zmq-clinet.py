import sys
import zmq

port = "5556"
if len(sys.argv) > 1:
    port =  sys.argv[1]
    int(port)
    
if len(sys.argv) > 2:
    port1 =  sys.argv[2]
    int(port1)

# Socket to talk to server
context = zmq.Context()
socket = context.socket(zmq.SUB)

print "Collecting updates from weather server..."
socket.connect ("tcp://192.168.1.233:%s" % port)

if len(sys.argv) > 2:
    socket.connect ("tcp://192.168.1.233:%s" % port1)

# Subscribe to zipcode, default is NYC, 10001
topicfilter = "10001"
socket.setsockopt(zmq.SUBSCRIBE, topicfilter)
socket.setsockopt(zmq.SUBSCRIBE, "1")
socket.setsockopt(zmq.SUBSCRIBE, "10002")

# Process 5 updates
total_value = 0
for update_nbr in range (5):
    string = socket.recv()
    #topic, messagedata = string.split()
    #total_value += int(messagedata)
    print string

print "Average messagedata value for topic '%s' was %dF" % (topicfilter, total_value / update_nbr)
      
