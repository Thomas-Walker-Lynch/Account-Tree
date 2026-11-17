# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Request·Composer - the person's side of the request gate.

The person's Account-Tree program is its own Man-In-Grey orchestrator: it
composes a journal of one request with Man-In-Grey's journal interface, from
the definition in Request·Language.py, invokes the request gate with it
through Man_In_Grey.admit, and decodes the result. It runs under the
person's account, which the gate learns from the kernel as its real uid.

  RequestError        a request was refused or failed; it carries what the
                      gate, the guard and the interpreter said
  enter               ask to enter a child account; the terminal of the session

The gate is the installed one, setuid root. The journal is composed against
the definition beside this file, so this file and the installed guard are
to be of the same installation; when they differ, the guard refuses the
journal as composed against another definition.
"""

import os ,sys ,tempfile
from pathlib import Path

DIRPA__HERE = Path(__file__).resolve().parent
FPA__GATE__REQUEST = Path("/usr/local/lib/Account-Tree/Account_Tree__Gate/Account_Tree__Gate·Request")

def dirpa__Man_In_Grey():
  """
  Man-In-Grey's modules: Man_In_Grey/ beside this file where Account-Tree is
  installed, or the project's Man-In-Grey dependency where it is promoted.
  """
  installed = DIRPA__HERE / "Man_In_Grey"
  if installed.is_dir():
    return installed
  return (DIRPA__HERE.parent.parent / "shared" / "project-dependency" / "Man-In-Grey" / "Man_In_Grey").resolve()

if str(dirpa__Man_In_Grey()) not in sys.path:
  sys.path.insert(1 ,str(dirpa__Man_In_Grey()))

import Language
import Journal
import Journal·Interface
import Man_In_Grey
import Request·Language as language_module


class RequestError(Exception):
  """A request was refused or failed. Its output is what the gate, guard and interpreter said."""
  def __init__(self ,message ,output=""):
    super().__init__(message)
    self.output = output


def definition():
  return Language.Definition(language_module.NAME ,language_module.DEFINITION)

def admit__quiet(journal_bytes):
  """
  Invoke the request gate with the journal, keeping what the gate, the guard
  and the interpreter write off the person's terminal: it goes to the system
  log anyway, and is handed back to be shown when the request fails.
  Returns (status ,result ,list__fd ,output).
  """
  if not FPA__GATE__REQUEST.is_file():
    raise RequestError(f"the request gate is not installed at {FPA__GATE__REQUEST}; run Account-Tree_install")
  with tempfile.TemporaryFile() as output:
    sys.stdout.flush(); sys.stderr.flush()
    saved = os.dup(1) ,os.dup(2)
    os.dup2(output.fileno() ,1); os.dup2(output.fileno() ,2)
    try:
      status ,result ,list__fd = Man_In_Grey.admit(FPA__GATE__REQUEST ,journal_bytes)
    finally:
      os.dup2(saved[0] ,1); os.dup2(saved[1] ,2)
      os.close(saved[0]); os.close(saved[1])
    output.seek(0)
    return status ,result ,list__fd ,output.read().decode("utf-8" ,"replace")

def display__here():
  """
  The display of the session this program runs in, as the enter request
  takes it: DISPLAY, the Wayland socket's absolute path, and the X
  authority file, each empty where there is none.
  """
  wayland = os.environ.get("WAYLAND_DISPLAY" ,"")
  if wayland and not os.path.isabs(wayland):
    dirpa__runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    wayland = os.path.join(dirpa__runtime ,wayland)
  return {
    "display": os.environ.get("DISPLAY" ,"")
    ,"wayland_display": os.path.normpath(wayland) if wayland else ""
    ,"xauthority": os.environ.get("XAUTHORITY" ,"") if os.environ.get("DISPLAY") else ""
  }

def enter(account_name ,display=None ,terminal_type=None):
  """
  Ask to enter account_name, a child account below this program's account.
  Returns the descriptor of the master side of the session's terminal, which
  is the caller's to relay to and close. Raises RequestError.
  """
  composed = Journal·Interface.JournalComposed(definition())
  journal_iface = Journal·Interface.JournalInterface(composed)
  session = journal_iface.declare("session" ,"session")
  journal_iface.enter(account_name ,display if display is not None else display__here()
                      ,terminal_type or os.environ.get("TERM") or "dumb" ,session)
  journal_iface.result(session)
  status ,result ,list__fd ,output = admit__quiet(composed.encode())
  try:
    if status != 0 or not result:
      raise RequestError(f"the request to enter {account_name} was not carried out (gate exit status {status})" ,output)
    try:
      type_name ,value = Journal.decode_result(result ,list__fd)
    except Journal.JournalError as error:
      raise RequestError(f"the request gate handed back a result that cannot be read: {error}" ,output)
    if type_name != "session" or type(value) is not dict or type(value.get("pty")) is not int:
      raise RequestError(f"the request gate handed back a {type_name}, not a session" ,output)
  except RequestError:
    for fd in list__fd:
      os.close(fd)
    raise
  return value["pty"]
