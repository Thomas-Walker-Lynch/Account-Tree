# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Request·LibraryInstruction - the implementation of the Request instructions.

The interpreter makes one LibraryInstruction for each journal and calls its
functions, one for each operation specifier of the definition,
Request·Language.py, given each instruction's arguments by position. It runs
with root's rights, once the guard has passed the journal.

enter starts a login session of a child account on a new terminal, as
machinectl shell does, and as systemd-machined does for it:

  1. it lets the child account open windows on the asking account's display:
     an ACL on the Wayland socket and on the runtime directory holding it, and
     for X, xhost +SI:localuser:<child>, run under the asking account with its
     X authority file;
  2. it makes a pseudo-terminal pair, and gives the side a session uses, the
     slave, to the child account;
  3. it has systemd start the child account's login shell on that slave as a
     transient service, under the child account, with PAMName=login, so the
     session is opened through PAM as a login is: logind registers it, the
     child account's user manager starts, and XDG_RUNTIME_DIR and the
     session bus are set. Type=exec makes systemd-run return once the shell
     has been executed, so the shell holds the terminal by then;
  4. it writes the master side, a descriptor, to the session variable. The
     interpreter sends it to the gate beside the result, and the gate hands
     it to the asking program, which relays its own terminal to it.

A process the session starts runs under the child account. The display, once
given to the account, is not taken back when the session ends; it lasts as long as the
display does.

make_child_account and deallocate call the work functions of ChildAccount.py,
share_with and share_remove those of Share.py, and the sound requests those
of Sound.py, which Account-Tree_admin calls too. Those report through a
Common.Log, which prints to standard output; the interpreter's standard
output is for its verdict alone, so they are given LogInterpreter, which
reports each line as the interpreter's own, on standard error.
"""

import grp ,os ,pwd ,secrets ,subprocess

import Common
import ChildAccount
import Notice
import Share
import Sound
import SystemAccount as sa

SHELL__DEFAULT = "/bin/sh"
FPA__ACCOUNT_TREE = os.path.join(os.path.dirname(os.path.realpath(__file__)) ,"Account-Tree")


class RequestError(Exception):
  """A request cannot be carried out."""


def shell__of(entry):
  "the login shell of a system account, or SHELL__DEFAULT when it names none"
  return entry.pw_shell if entry.pw_shell and os.path.isabs(entry.pw_shell) else SHELL__DEFAULT

def session__environment(display):
  """
  (the session type, tty, x11 or wayland ,the systemd-run --setenv
  arguments) for a session given display
  """
  if display["wayland_display"]:
    session_type = "wayland"
  elif display["display"]:
    session_type = "x11"
  else:
    session_type = "tty"
  list__setenv = [f"--setenv=XDG_SESSION_TYPE={session_type}"]
  if display["display"]:
    list__setenv.append(f"--setenv=DISPLAY={display['display']}")
  if display["wayland_display"]:
    list__setenv.append(f"--setenv=WAYLAND_DISPLAY={display['wayland_display']}")
  return session_type ,list__setenv

def run(log ,argument ,what ,**option):
  """
  Run a program with its output kept from the gate's standard output, which
  is for the verdict alone; its error lines are logged. Raises RequestError
  when it fails.
  """
  try:
    completed = subprocess.run(argument ,capture_output=True ,text=True ,**option)
  except OSError as error:
    raise RequestError(f"{what}: cannot run {argument[0]}: {error.strerror}")
  for line in completed.stderr.splitlines():
    if line.strip(): log("said" ,f"{argument[0]}: {line}")
  if completed.returncode != 0:
    raise RequestError(f"{what}: {argument[0]} exited {completed.returncode}")
  return completed.stdout

class LogInterpreter(Common.Log):
  """A Common.Log whose lines are the interpreter's: each goes to log(tag ,message), on standard error."""

  def __init__(self ,log):
    super().__init__(False)
    self._log = log
    self.list__error = []

  def line(self ,tag ,subject ,reason=None):
    self.count[tag] = self.count.get(tag ,0) + 1
    self._log(tag.replace(" " ,"-") ,subject + (f" ({reason})" if reason else ""))

  def error(self ,subject ,reason):
    self.count_of__error += 1
    self.list__error.append(f"{subject}: {reason}")
    self._log("error" ,f"{subject}: {reason}")

  def failure(self ,what):
    "a RequestError saying what stopped, from the errors logged"
    return RequestError(f"{what}: " + ("; ".join(self.list__error) or "it stopped"))

class LibraryInstruction:

  def __init__(self ,constraint ,gate_invoking_account ,log):
    self._log = log
    self._asking = pwd.getpwnam(gate_invoking_account)
    self._list__fd__close = []   # descriptors to close in release(); not one handed back

  # ------------------------------------------------------------------------------
  # the display

  def display__give(self ,child ,display):
    asking = self._asking
    if display["wayland_display"]:
      socket = display["wayland_display"]
      run(self._log ,["setfacl" ,"-m" ,f"u:{child.pw_uid}:x" ,os.path.dirname(socket)] ,"the Wayland socket's directory")
      run(self._log ,["setfacl" ,"-m" ,f"u:{child.pw_uid}:rw" ,socket] ,"the Wayland socket")
      self._log("given" ,f"{child.pw_name} the Wayland socket {socket}")
    if display["display"]:
      env = {"PATH": "/usr/bin:/bin" ,"HOME": asking.pw_dir ,"DISPLAY": display["display"]}
      if display["xauthority"]:
        env["XAUTHORITY"] = display["xauthority"]
      # under the asking account: its X authority file is its own, and the
      # display is given with no more right than the display's owner has
      run(self._log ,["xhost" ,f"+SI:localuser:{child.pw_name}"] ,f"the X display {display['display']}"
          ,env=env ,cwd="/" ,user=asking.pw_uid ,group=asking.pw_gid
          ,extra_groups=os.getgrouplist(asking.pw_name ,asking.pw_gid))
      self._log("given" ,f"{child.pw_name} the X display {display['display']}")

  # ------------------------------------------------------------------------------
  # the instructions

  def enter(self ,account_name ,display ,terminal_type ,session):
    child = sa.system_account(account_name)
    if child is None:
      raise RequestError(f"there is no system account {account_name}")
    self.display__give(child ,display)

    fd__master ,fd__slave = os.openpty()
    self._list__fd__close += [fd__master ,fd__slave]
    fpa__slave = os.ttyname(fd__slave)
    try:
      gid__tty = grp.getgrnam("tty").gr_gid
    except KeyError:
      gid__tty = child.pw_gid
    os.fchown(fd__slave ,child.pw_uid ,gid__tty)
    os.fchmod(fd__slave ,0o620)

    shell = shell__of(child)
    unit = f"Account-Tree_enter-{child.pw_uid}-{secrets.token_hex(4)}"
    session_type ,list__setenv = session__environment(display)
    list__setenv.append(f"--setenv=TERM={terminal_type}")
    # The login shell is started by sh, which first gives the display to the
    # child account's user manager, so the programs it starts, such as those
    # D-Bus activates, find the display too.
    if session_type == "tty":
      command = [shell ,"-l"]
    else:
      command = ["/bin/sh" ,"-c"
                 ,'systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XDG_SESSION_TYPE 2>/dev/null; exec "$0" -l'
                 ,shell]
    run(self._log ,["systemd-run" ,"--quiet" ,"--collect" ,f"--unit={unit}" ,"--service-type=exec"
                    ,f"--uid={child.pw_uid}" ,f"--gid={child.pw_gid}"
                    ,"--property=PAMName=login"
                    ,f"--property=TTYPath={fpa__slave}"
                    ,"--property=StandardInput=tty" ,"--property=StandardOutput=tty" ,"--property=StandardError=tty"
                    ,"--property=TTYReset=yes" ,"--property=TTYVHangup=yes"
                    ,"--property=WorkingDirectory=~"
                    ,*list__setenv ,"--" ,*command]
        ,f"the session of {child.pw_name}")
    self._log("entered" ,f"{child.pw_name} on {fpa__slave}, as the unit {unit}.service, shell {shell}")
    self._list__fd__close.remove(fd__master)
    session.append({"pty": fd__master})

  def window_open(self ,account_name ,display):
    """
    The window runs as a session of the child account, as enter's shell
    does, with no terminal: the child's login shell, so the window finds the
    programs and the Python a shell of the child's would, gives the display to
    the child's user manager and runs Account-Tree window for the child. What
    the window writes goes to the journal, under the unit's name.
    """
    child = sa.system_account(account_name)
    if child is None:
      raise RequestError(f"there is no system account {account_name}")
    self.display__give(child ,display)
    unit = f"Account-Tree_window-{child.pw_uid}-{secrets.token_hex(4)}"
    _ ,list__setenv = session__environment(display)
    command = [shell__of(child) ,"-l" ,"-c"
               ,'systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XDG_SESSION_TYPE 2>/dev/null; exec "$0" window .'
               ,FPA__ACCOUNT_TREE]
    run(self._log ,["systemd-run" ,"--quiet" ,"--collect" ,f"--unit={unit}" ,"--service-type=exec"
                    ,f"--uid={child.pw_uid}" ,f"--gid={child.pw_gid}"
                    ,"--property=PAMName=login"
                    ,"--property=StandardInput=null" ,"--property=StandardOutput=journal" ,"--property=StandardError=journal"
                    ,"--property=WorkingDirectory=~"
                    ,*list__setenv ,"--" ,*command]
        ,f"the window of {child.pw_name}")
    self._log("opened" ,f"the window of {child.pw_name}, under {child.pw_name}, as the unit {unit}.service;"
              f" what it writes is read with journalctl -u {unit}")

  def make_child_account(self ,account_name ,made):
    log = LogInterpreter(self._log)
    parent ,short_name = account_name.rsplit("·" ,1)
    result = ChildAccount.child__make(parent ,short_name ,log ,False)
    if result is None:
      raise log.failure(f"making {account_name}")
    made.append(result)
    Notice.notice__give(Notice.login__of_name(account_name) ,log ,False)

  def deallocate(self ,account_name):
    log = LogInterpreter(self._log)
    if not ChildAccount.child__deallocate(account_name ,log ,False):
      raise log.failure(f"deallocating {account_name}")

  def share_with(self ,account_name ,list__account_name):
    log = LogInterpreter(self._log)
    if not Share.share__with(account_name ,list__account_name ,log ,False):
      raise log.failure(f"sharing {account_name}")
    Notice.notice__give(Notice.login__of_name(account_name) ,log ,False)

  def share_remove(self ,account_name ,list__account_name):
    log = LogInterpreter(self._log)
    if not Share.share__remove(account_name ,list__account_name ,log ,False):
      raise log.failure(f"ending shares of {account_name}")
    Notice.notice__give(Notice.login__of_name(account_name) ,log ,False)

  def sound_show(self ,account_name ,sound):
    log = LogInterpreter(self._log)
    value = Sound.sound__of(self._asking.pw_name ,account_name ,log)
    if value is None:
      raise log.failure(f"showing the sound of {account_name}")
    sound.append(value)

  def sound_permit_issue(self ,account_name ,permit):
    log = LogInterpreter(self._log)
    if not Sound.permit__issue(self._asking.pw_name ,account_name ,permit ,True ,log ,False):
      raise log.failure(f"issuing {account_name} the permit {permit}")

  def sound_permit_revoke(self ,account_name ,permit):
    log = LogInterpreter(self._log)
    if not Sound.permit__issue(self._asking.pw_name ,account_name ,permit ,False ,log ,False):
      raise log.failure(f"revoking the permit {permit} of {account_name}")

  def sound_connection_set(self ,account_name ,text__connection):
    log = LogInterpreter(self._log)
    if not Sound.connection__set(self._asking.pw_name ,account_name ,text__connection ,log ,False):
      raise log.failure(f"setting the connection table of {account_name}")

  def sound_connection_reset(self ,account_name):
    log = LogInterpreter(self._log)
    if not Sound.connection__reset(self._asking.pw_name ,account_name ,log ,False):
      raise log.failure(f"resetting the connection table of {account_name}")

  def sound_bus_set(self ,bus__number ,bus__name):
    log = LogInterpreter(self._log)
    if not Sound.bus__set(self._asking.pw_name ,bus__number ,bus__name ,log ,False):
      raise log.failure(f"setting bus {bus__number}")

  def sound_bus_remove(self ,bus__number):
    log = LogInterpreter(self._log)
    if not Sound.bus__remove(self._asking.pw_name ,bus__number ,log ,False):
      raise log.failure(f"removing bus {bus__number}")

  def sound_route_show(self ,route):
    log = LogInterpreter(self._log)
    value = Sound.route__of(self._asking.pw_name ,log)
    if value is None:
      raise log.failure("showing the route")
    route.append(value)

  def release(self):
    # the slave is held by the session now; the master, when it is handed
    # back, is closed by Interpreter.write_result once sent
    for fd in self._list__fd__close:
      try:
        os.close(fd)
      except OSError:
        pass
    self._list__fd__close = []
