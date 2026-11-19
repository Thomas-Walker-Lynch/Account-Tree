# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Notice - telling the windows and routers of a tree that its records changed

When the request interpreter or the administrator changes a tree, its
accounts, shares, permits, buses or connection tables, it writes the tree's
notice file:

  /run/Account-Tree/notice/<login account>    root's, mode 0644, in a
                                              directory of mode 0711

Every window and every sound router of the tree holds a watch on that file,
through Linux's inotify, and on a notice reads again what it shows or does,
through the request gate as before. The notice carries nothing but that a
change was made; what changed is read with the reader's own authority. It is
a message from one writer to every reader at once, and no list of readers is
kept: the kernel holds the watches, and a window that has closed holds none.

The directory can be passed through and not listed, so an account learns of
another tree's notice only by naming its login account, and then only when a
change was made.

  notice__give       write a tree's notice
  Watch              a watch on a tree's notice, for a window or a router
"""

import os ,time
from pathlib import Path

import Kernel
from Kernel import KernelError
from Common import SEPARATOR

DIRPA__NOTICE = Path("/run/Account-Tree/notice")


def fpa__notice(login_name):
  return DIRPA__NOTICE / login_name

def login__of_name(system_account__name):
  "the login account of the tree an account name is in: its first part"
  return system_account__name.split(SEPARATOR ,1)[0]

def notice__give(login_name ,log ,preview):
  """
  Write the notice of login_name's tree, in place, so the watches on it,
  which are on the file's inode, see it written.
  """
  if preview:
    log.line("noticed" ,f"the tree of {login_name}" ,"its windows and routers read again"); return
  # mkdir's mode is cut by the umask, so the mode is given after
  for dirpa in (DIRPA__NOTICE.parent ,DIRPA__NOTICE):
    if not dirpa.is_dir():
      os.mkdir(dirpa ,0o711)
    if os.stat(dirpa).st_mode & 0o7777 != 0o711:
      os.chmod(dirpa ,0o711)
  fpa = fpa__notice(login_name)
  fd = os.open(fpa ,os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC | os.O_NOFOLLOW ,0o644)
  try:
    os.fchmod(fd ,0o644)
    os.write(fd ,f"{time.time():.6f}\n".encode())
  finally:
    os.close(fd)
  log.line("noticed" ,f"the tree of {login_name}" ,"its windows and routers read again")


class Watch:
  """
  A watch on the notice of login_name's tree. open() makes it, when the
  notice file exists; fd is then the descriptor to wait on, and read() says
  whether a notice came. The file is made at the tree's first change since
  the system started, so a watch that cannot be made yet is tried again by
  its owner, with open(), and a notice taken as come once it can be.
  """

  def __init__(self ,login_name):
    self.login_name = login_name
    self.fd = None

  def open(self):
    "True when the watch is held, after this call"
    if self.fd is not None:
      return True
    try:
      self.fd = Kernel.inotify__watch(fpa__notice(self.login_name))
    except KernelError:
      return False
    return True

  def read(self):
    "whether a notice came; the watch is closed when the file went, for open() to make again"
    if self.fd is None:
      return False
    is__written ,is__ended = Kernel.inotify__read(self.fd)
    if is__ended:
      self.close()
    return is__written or is__ended

  def close(self):
    if self.fd is not None:
      os.close(self.fd)
      self.fd = None
