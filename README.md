# Audera

`audera` is an open-source multi-room audio streaming system written in Python for DIY home entertainment enthusiasts.

## Implementation architecture
The following section describes different options for deploying `audera`, either as a **standalone streaming system** or **self-hosted with Home Assistant**.

### Standalone streaming system
The `audera` server can be deployed on a Raspberry-pi, where the Raspberry-pi manages the audio input device, capturing and streaming all audio from the input device over the network. Any number of `audera` clients can connect securely to the `audera` server over TCP and can play audio through any speaker or output interface.

The following example is a simple Raspberry-pi only based implementation,
```
                           +------------+      +------------+                 
                           |       rp-i |      |     rp-i n |+       +---------+
                           |            |      |            ||+      |       n |
                           |   audera   | TCP  |   audera   |||      | active  |
    Streamer ---->     AUX +  {server}  <------>  {client}  ||+ AUX -> speaker |
                           |            |      |            |||      |         |
                           |            |      |            |||      |         |
                           +------------+      +------------+||      +---------+
                                                 +-----------+|               
                                                  +-----------+               
```

The Raspberry-pi hardware can be improved by add-on DACs and Amplifiers (like those available from Hifiberry), which can offer additional audio input / output interfaces and higher quality audio capture, streaming and playback.

The following example extends the simple Raspberry-pi implementation with Hifiberry DAC and Amplifier add-on boards.
```
                                         +------------+      +------------+                                
                           +-----------+ |       rp-i |      |     rp-i n |+  +-----------+     +---------+
          TV ----> OPTICAL +           | |            |      |            ||+ |           |     |       n |
                           | Hifiberry | |   audera   | TCP  |   audera   ||| | Hifiberry |     | passive |
                           | Digi+ I/O -->  {server}  <------>  {client}  ||-->   AMP2    ------> speaker |
    Streamer ---->     AUX +           | |            |      |            ||| |           |     |         |
                           +-----------+ |            |      |            ||| +-----------+     |         |
                                         +------------+      +------------+||                   +---------+
                                                               +-----------+|                              
                                                                +-----------+                              
```

### Self-hosted with Home Assistant
The `audera` server can be deployed as a docker container on a home-server, which adds a virtual line-out audio device into the Home Assistant ecosystem that can be used to direct audio to `audera` clients. The virtual line-out can be used with any Home Assistant media player, like Music Assistant, which offers connectivity to local media files, streaming services like Spotify and online radio.
```
    +---------------------------------------------+                                 
    |                                             |                                 
    | unraid {server}                             |                                 
    |                                             |                                 
    |  +------------+             +------------+  |  +------------+                 
    |  |            |             |            |  |  |          n |+       +-------+
    |  |            |   virtual   |            |  |  |            ||+      |     n |
    |  |    Home    |   line-out  |   audera   | TCP |   audera   |||      |       |
    |  | Assisstant -------------->  {server}  <----->  {client}  ||------>|speaker|
    |  |            |             |            |  |  |            |||      |       |
    |  |            -------+      |            |  |  |            |||      |       |
    |  +------------+      |      +------------+  |  +------------+||      +-------+
    |                      |                      |    +-----------+|               
    +----------------------|----------------------+     +-----------+               
                           |                                                        
                           |      +------------+                                    
                           |      |            |                                    
                           |      |            |                                    
                           |      |            |                                    
                           +------> Chromecast |                                    
                                  |            |                                    
                                  |            |                                    
                                  +------------+                                    
```