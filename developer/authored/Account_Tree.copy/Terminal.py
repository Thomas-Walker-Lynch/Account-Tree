# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Terminal - relaying this program's terminal to another terminal's master side.

A pseudo-terminal is a pair: the slave side, which a session's shell has as
its terminal, and the master side, which stands where a keyboard and screen
would be. Whatever is written to the master the shell reads as typed, and
whatever the shell writes is read from the master. relay copies the bytes
both ways between this program's own terminal and a master it holds, as
machinectl shell and ssh do.

This program's terminal is put in raw mode for the relay: no line editing,
no echo, no signal keys, so that each key reaches the session as it is
pressed and the session's own terminal does that work. The mode is put back
when the relay ends. A change of this terminal's size, signalled by
SIGWINCH, is passed on to the session's terminal, which signals the session.

The relay ends when the session's terminal is hung up: when the session's
last process holding it ends, reading the master fails with EIO.
"""

import errno ,fcntl ,os ,select ,signal ,termios ,tty

def write_all(fd ,data):
  view = memoryview(data)
  while view:
    view = view[os.write(fd ,view):]

def size__pass_on(fd__from ,fd__to):
  "give fd__to the window size of fd__from, when fd__from is a terminal"
  try:
    size = fcntl.ioctl(fd__from ,termios.TIOCGWINSZ ,b"\0" * 8)
    fcntl.ioctl(fd__to ,termios.TIOCSWINSZ ,size)
  except OSError:
    pass

def relay(fd__master ,fd__in=0 ,fd__out=1):
  """
  Copy between this program's terminal, read from fd__in and written to
  fd__out, and the master side fd__master, until the session hangs up. When
  fd__in is not a terminal, its end is passed on as the end-of-file key.
  """
  is__terminal = os.isatty(fd__in)
  mode__saved = termios.tcgetattr(fd__in) if is__terminal else None
  handler__saved = signal.signal(signal.SIGWINCH ,lambda number ,frame: size__pass_on(fd__in ,fd__master))
  try:
    size__pass_on(fd__in ,fd__master)
    if is__terminal:
      tty.setraw(fd__in ,termios.TCSANOW)
    is__open__in = True
    while True:
      list__read = [fd__master] + ([fd__in] if is__open__in else [])
      ready ,_ ,_ = select.select(list__read ,[] ,[])
      if fd__master in ready:
        try:
          data = os.read(fd__master ,1 << 16)
        except OSError as error:
          if error.errno == errno.EIO: break
          raise
        if not data: break
        write_all(fd__out ,data)
      if fd__in in ready:
        data = os.read(fd__in ,1 << 16)
        if data:
          write_all(fd__master ,data)
        else:
          is__open__in = False
          if not is__terminal:
            write_all(fd__master ,b"\x04")
  finally:
    if mode__saved is not None:
      termios.tcsetattr(fd__in ,termios.TCSADRAIN ,mode__saved)
    signal.signal(signal.SIGWINCH ,handler__saved)
