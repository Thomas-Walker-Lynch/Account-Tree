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
  request             compose a journal of one request, give it to the gate,
                      and decode the result
  enter               ask to enter a child account; the terminal of the session
  make_child_account  ask to make an account below this one; its name and uids
  deallocate          ask to deallocate an account below this one
  share_with          ask to share an account with others
  share_remove        ask to end shares
  sound_show          ask what the window shows of an account's sound
  sound_permit_set    ask to set or clear a permit
  sound_connection_set   ask to replace a connection table; with text None,
                      to put the default one back
  sound_bus_set       ask to make or rename a bus
  sound_bus_remove    ask to remove a bus
  sound_route_show    ask what this account's router is to do
  list__done          what the interpreter reported doing, from a request's output

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

def request(what ,operation ,list__argument ,result_type=None):
  """
  Compose a journal of one request, operation(*list__argument), writing its
  last argument when result_type is given, and give it to the request gate.
  Returns (value ,output): the result's value, None for a request with no
  result, and what the gate, the guard and the interpreter said. Raises
  RequestError, naming what was asked, as what.
  """
  composed = Journal·Interface.JournalComposed(definition())
  journal_iface = Journal·Interface.JournalInterface(composed)
  if result_type is not None:
    variable = journal_iface.declare(result_type ,result_type)
    getattr(journal_iface ,operation)(*list__argument ,variable)
    journal_iface.result(variable)
  else:
    getattr(journal_iface ,operation)(*list__argument)
  status ,result ,list__fd ,output = admit__quiet(composed.encode())
  try:
    if status != 0:
      raise RequestError(f"{what} was not carried out (gate exit status {status})" ,output)
    if result_type is None:
      return None ,output
    if not result:
      raise RequestError(f"{what}: the request gate handed back no result" ,output)
    try:
      type_name ,value = Journal.decode_result(result ,list__fd)
    except Journal.JournalError as error:
      raise RequestError(f"{what}: the request gate handed back a result that cannot be read: {error}" ,output)
    problem = definition().value_problem(value ,result_type ,"the result") if type_name == result_type else f"the result is a {type_name}"
    if problem:
      raise RequestError(f"{what}: {problem}, not a {result_type}" ,output)
  except RequestError:
    for fd in list__fd:
      os.close(fd)
    raise
  return value ,output

def list__done(output):
  "the lines the interpreter wrote, its report of what it did, without the tag that marks them"
  return [line[len("interpreter: "):] for line in output.splitlines() if line.startswith("interpreter: ")]

def enter(account_name ,display=None ,terminal_type=None):
  """
  Ask to enter account_name, a child account below this program's account.
  Returns the descriptor of the master side of the session's terminal, which
  is the caller's to relay to and close. Raises RequestError.
  """
  value ,_ = request(f"the request to enter {account_name}" ,"enter"
                     ,[account_name ,display if display is not None else display__here()
                       ,terminal_type or os.environ.get("TERM") or "dumb"] ,"session")
  return value["pty"]

def make_child_account(account_name):
  """
  Ask to make the account account_name, an absolute name whose parent is
  this account or one below it. Returns ({"name" ,"database_uid"
  ,"system_uid"} ,output). Raises RequestError.
  """
  return request(f"the request to make {account_name}" ,"make_child_account" ,[account_name] ,"made")

def share_with(account_name ,list__member):
  "Ask to share account_name with each account of list__member. Returns output. Raises RequestError."
  return request(f"the request to share {account_name}" ,"share_with" ,[account_name ,list(list__member)])[1]

def share_remove(account_name ,list__member):
  "Ask to end the share of account_name with each account of list__member. Returns output. Raises RequestError."
  return request(f"the request to end shares of {account_name}" ,"share_remove" ,[account_name ,list(list__member)])[1]

def deallocate(account_name):
  "Ask to deallocate account_name. Returns output. Raises RequestError."
  return request(f"the request to deallocate {account_name}" ,"deallocate" ,[account_name])[1]

def sound_show(account_name):
  "Ask what the window shows of account_name's sound; the sound value of Request·Language.py. Raises RequestError."
  return request(f"the request to show the sound of {account_name}" ,"sound_show" ,[account_name] ,"sound")[0]

def sound_permit_set(account_name ,permit ,is__set):
  "Ask to set or clear account_name's permit, as 1.gather or @output. Returns output. Raises RequestError."
  return request(f"the request to {'set' if is__set else 'clear'} the permit {permit} of {account_name}"
                 ,"sound_permit_set" ,[account_name ,permit ,is__set])[1]

def sound_connection_set(account_name ,text):
  """
  Ask to replace account_name's connection table with text, or, with text
  None, to put its default table back. Returns output. Raises RequestError.
  """
  if text is None:
    return request(f"the request to reset the connection table of {account_name}" ,"sound_connection_reset" ,[account_name])[1]
  return request(f"the request to set the connection table of {account_name}" ,"sound_connection_set" ,[account_name ,text])[1]

def sound_bus_set(bus__number ,bus__name):
  "Ask to make or rename bus bus__number of this account's tree. Returns output. Raises RequestError."
  return request(f"the request to set bus {bus__number}" ,"sound_bus_set" ,[bus__number ,bus__name])[1]

def sound_bus_remove(bus__number):
  "Ask to remove bus bus__number of this account's tree. Returns output. Raises RequestError."
  return request(f"the request to remove bus {bus__number}" ,"sound_bus_remove" ,[bus__number])[1]

def sound_route_show():
  "Ask what this account's router is to do; the route value of Request·Language.py. Raises RequestError."
  return request("the request to show the route" ,"sound_route_show" ,[] ,"route")[0]
