     ________  ___  ___  ________  _______  ________  ________     
    |\   __  \|\  \|\  \|\   ___ \|\   ___\|\   __  \|\   __  \    
    \ \  \|\  \ \  \\\  \ \  \_|\ \ \  \__|\ \  \|\  \ \  \|\  \   
     \ \   __  \ \  \\\  \ \  \ \\ \ \   __\\ \      /\ \   __  \  
      \ \  \ \  \ \  \\\  \ \  \_\\ \ \  \_|_\ \  \  \ \ \  \ \  \ 
       \ \__\ \__\ \______/\ \______/\ \______\ \__\\ _\\ \__\ \__\
        \|__|\|__|\|______| \|______| \|______|\|__|\|__|\|__|\|__|

`alpha-release` coming soon!

`audera` is an open-source multi-room audio streaming system written in Python for DIY home audio enthusiasts.

## Implementation architecture
`audera` can be deployed either as a **standalone streaming system** or **self-hosted with Home Assistant**.

### Standalone streaming system
The `audera` streamer can be deployed on a Raspberry-pi, where the Raspberry-pi manages the audio input device, capturing and streaming all audio from the input device over the network. Any number of `audera` remote audio output players can connect securely to the `audera` streamer over TCP and can play audio through any speaker or output interface.

The following example is a simple Raspberry-pi only based implementation with auxiliary input / output(s) that supports active speakers,
```
                           +------------+      +------------+                 
                           |        rpi |      |      rpi n |+       +---------+
                           |            |      |            ||+      |       n |+
                           |   audera   | TCP  |   audera   |||      | active  ||+
    Streamer ---->     AUX + {streamer} <------>  {player}  + AUX ---> speaker |||
                           |            |      |            |||      |         |||
                           |            |      |            |||      |         |||
                           +------------+      +------------+||      +---------+||
                                                 +-----------+|       +---------+|
                                                  +-----------+        +---------+
```

The Raspberry-pi hardware can be improved by add-on DACs and amplifiers (like those available from Hifiberry), which can offer additional audio input / output interfaces and higher quality audio capture, streaming and playback.

The following example extends the simple Raspberry-pi implementation with Hifiberry DAC and amplifier add-on boards, which supports much higher fidelity passive speakers,
```
                           +-----------+                               
          TV ----> OPTICAL +           | +------------+      +------------+                                
                           | Hifiberry | |        rpi |      |      rpi n |+  +-----------+     +---------+
                           | Digi+ I/O -->            |      |            ||+ |         n |+    |       n |+
                   COAXIAL +           | |   audera   | TCP  |   audera   ||| | Hifiberry ||+   | passive ||+
                           +-----------+ | {streamer} <------>  {player}  ---->   AMP2    ------> speaker |||
                                         |            |      |            ||| |           |||   |         |||
          Streamer ----------------> AUX +            |      |            ||| +-----------+||   |         |||
                                         +------------+      +------------+||  +-----------+|   +---------+||
                                                               +-----------+|   +-----------+    +---------+|
                                                                +-----------+                     +---------+
```

### Self-hosted with Home Assistant
The `audera` players are natively discoverable by audio source devices that can be integrated directly into Home Assistant and managed by media players, like Music Assistant, which offers the ability to stream audio from local media files, streaming services, like Spotify, and online radio.
```
    +---------------------------------------+                                 
    |  unraid{streamer}                     |
    |  +----------------------------------+ |                                 
    |  |  Home Assistant   +------------+ | |  +------------+                 
    |  |                   |            | | |  |      rpi n |+       +---------+
    |  |                   |            | | |  |            ||+      |       n |+
    |  |                   |   Music    | | |  |   audera   |||      |         ||+
    |  |                   |  Assistant ------->  {player}  -------- > speaker |||
    |  |                   |            | | |  |            |||      |         |||
    |  |                   |            | | |  |            |||      |         |||
    |  |                   +------------+ | |  +------------+||      +---------+||
    |  +----------------------------------+ |    +-----------+|       +---------+|
    |                                       |     +-----------+        +---------+
    +---------------------------------------+
                                 
```