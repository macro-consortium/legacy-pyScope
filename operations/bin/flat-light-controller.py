#!/usr/bin/env python

# Gemini Flat light controller (National Control Devices Pulsar series)
# RLM + DL 19 Jan 2016

import socket
import struct
import binascii
import sys
 
# TCP port of light dimmer
TCP_IP = '192.168.1.22'
TCP_PORT = 2101
BUFFER_SIZE = 1024

# Get desired intensity level from command line or ask user
if len(sys.argv) == 2:
	Intensity = int(sys.argv[1])
else:
	Intensity = int(input('Enter intensity level (0-254): '))
if not 0 <= Intensity < 255:
	sys.exit('Intensity (%i) must be 0->254, exiting' % ans)
	
# Open socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((TCP_IP, TCP_PORT))

# Create 4 byte array
my_bytes = bytearray()
my_bytes.append(253);       my_bytes.append(0)
my_bytes.append(Intensity); my_bytes.append(1)

try:
    s.send(my_bytes)
finally:
    data = s.recv(BUFFER_SIZE)
    print(f'Lighting controller returned {data}')
#    if data != 'U': print('Failed')
    s.close()

