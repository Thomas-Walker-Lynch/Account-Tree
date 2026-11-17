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

A process the session starts runs under the child account. The grant of the
display is not taken back when the session ends; it lasts as long as the
display does.
"""

import grp ,os ,pwd ,secrets ,subprocess

import SystemAccount as sa

SHELL__DEFAULT = "/bin/sh"


class RequestError(Exception):
  """A request cannot be carried out."""


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

class LibraryInstruction:

  def __init__(self ,constraint ,gate_invoking_account ,log):
    self._log = log
    self._asking = pwd.getpwnam(gate_invoking_account)
    self._list__fd__close = []   # descriptors to close in release(); not one handed back

  # ------------------------------------------------------------------------------
  # the display

  def display__grant(self ,child ,display):
    asking = self._asking
    if display["wayland_display"]:
      socket = display["wayland_display"]
      run(self._log ,["setfacl" ,"-m" ,f"u:{child.pw_uid}:x" ,os.path.dirname(socket)] ,"the Wayland socket's directory")
      run(self._log ,["setfacl" ,"-m" ,f"u:{child.pw_uid}:rw" ,socket] ,"the Wayland socket")
      self._log("granted" ,f"{child.pw_name} the Wayland socket {socket}")
    if display["display"]:
      env = {"PATH": "/usr/bin:/bin" ,"HOME": asking.pw_dir ,"DISPLAY": display["display"]}
      if display["xauthority"]:
        env["XAUTHORITY"] = display["xauthority"]
      # under the asking account: its X authority file is its own, and the
      # grant is made with no more right than the display's owner has
      run(self._log ,["xhost" ,f"+SI:localuser:{child.pw_name}"] ,f"the X display {display['display']}"
          ,env=env ,cwd="/" ,user=asking.pw_uid ,group=asking.pw_gid
          ,extra_groups=os.getgrouplist(asking.pw_name ,asking.pw_gid))
      self._log("granted" ,f"{child.pw_name} the X display {display['display']}")

  # ------------------------------------------------------------------------------
  # the instructions

  def enter(self ,account_name ,display ,terminal_type ,session):
    child = sa.system_account(account_name)
    if child is None:
      raise RequestError(f"there is no system account {account_name}")
    self.display__grant(child ,display)

    fd__master ,fd__slave = os.openpty()
    self._list__fd__close += [fd__master ,fd__slave]
    fpa__slave = os.ttyname(fd__slave)
    try:
      gid__tty = grp.getgrnam("tty").gr_gid
    except KeyError:
      gid__tty = child.pw_gid
    os.fchown(fd__slave ,child.pw_uid ,gid__tty)
    os.fchmod(fd__slave ,0o620)

    shell = child.pw_shell if child.pw_shell and os.path.isabs(child.pw_shell) else SHELL__DEFAULT
    unit = f"Account-Tree_enter-{child.pw_uid}-{secrets.token_hex(4)}"
    if display["wayland_display"]:
      session_type = "wayland"
    elif display["display"]:
      session_type = "x11"
    else:
      session_type = "tty"
    list__setenv = [f"--setenv=TERM={terminal_type}" ,f"--setenv=XDG_SESSION_TYPE={session_type}"]
    if display["display"]:
      list__setenv.append(f"--setenv=DISPLAY={display['display']}")
    if display["wayland_display"]:
      list__setenv.append(f"--setenv=WAYLAND_DISPLAY={display['wayland_display']}")
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

  def release(self):
    # the slave is held by the session now; the master, when it is handed
    # back, is closed by Interpreter.write_result once sent
    for fd in self._list__fd__close:
      try:
        os.close(fd)
      except OSError:
        pass
    self._list__fd__close = []
