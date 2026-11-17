# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Request·GuardCheck - the request guard's checks of the Request language.

Made after Man-In-Grey's well-formed guard has checked the journal against
the definition in Request·Language.py. They are LIST__CHECK:

  language     a journal holds one request, and its literals have the form
               their instruction takes: an account name, a display whose
               texts are empty or of the form each takes, a terminal type
  constraint   the predicates at the top of the guard, Request·Guard.py:
               is__allowed_account
  record       what the account tree allows, read from the system database
               and the storage databases: the asking account is an account
               a person uses, kept by Account-Tree; the account a request
               names is below it, active, and has its home mounted; see
               Request·Record.py
  filesystem   the display the request names is the asking account's own:
               the Wayland socket is a socket in its runtime directory, owned
               by it, and the X authority file is a regular file owned by
               it, each reached through no symbolic link

The gate's real uid, which the kernel gave it, names the asking account, so
nothing in a journal can say who asks.

The implementation of the requests is in Request·LibraryInstruction.py.
"""

import os ,pwd ,re ,stat

from Journal import has__control ,clean
from Common import valid_name
import Request·Record as record
import SystemAccount as sa

PATTERN__DISPLAY = re.compile(r":[0-9]{1,4}(\.[0-9]{1,2})?")
PATTERN__TERMINAL_TYPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")


# --------------------------------------------------------------------------------
# value checks

def path__problem(value ,what):
  if not value.startswith("/"):
    return f"{what} {clean(repr(value))} is not an absolute path"
  if has__control(value):
    return f"{what} {clean(value)} holds a control character"
  if os.path.normpath(value) != value:
    return f"{what} {value!r} is not in normal form"
  return None

def display__problem(display):
  list__problem = []
  if display["display"] and not PATTERN__DISPLAY.fullmatch(display["display"]):
    list__problem.append(f"display {clean(repr(display['display']))} is not of the form :<n> or :<n>.<screen>")
  for key ,what in (("wayland_display" ,"Wayland socket") ,("xauthority" ,"X authority file")):
    if display[key]:
      problem = path__problem(display[key] ,what)
      if problem: list__problem.append(problem)
  if display["xauthority"] and not display["display"]:
    list__problem.append("an X authority file is given with no X display")
  return list__problem


# --------------------------------------------------------------------------------
# the guard's checks, each given the instructions as Guard·WellFormed.InstructionView

def literal(view):
  "the values of an instruction's arguments, None for a variable"
  return [argument.value for argument in view.list__argument]

def check_language(list__instruction_view ,data ,constraint ,gate_invoking_account):
  if len(list__instruction_view) != 1:
    return [f"a journal holds one request; this one holds {len(list__instruction_view)}"]
  list__problem = []
  view = list__instruction_view[0]
  if view.operation == "enter":
    account_name ,display ,terminal_type ,_ = literal(view)
    problem = valid_name(account_name)
    if problem:
      list__problem.append(f"@{view.index} enter: account {clean(repr(account_name))}: {problem}")
    list__problem += [f"@{view.index} enter: {p}" for p in display__problem(display)]
    if not PATTERN__TERMINAL_TYPE.fullmatch(terminal_type):
      list__problem.append(f"@{view.index} enter: terminal type {clean(repr(terminal_type))} is not a terminal type name")
  return list__problem

def check_constraint(list__instruction_view ,data ,constraint ,gate_invoking_account):
  "constraint is the guard, which holds the predicates; a predicate allows only by answering True"
  if constraint.is__allowed_account(gate_invoking_account) is not True:
    return [f"gate invoking account {clean(repr(gate_invoking_account))} is not allowed to give journals to this gate"]
  return []

def check_record(list__instruction_view ,data ,constraint ,gate_invoking_account):
  entry = sa.system_account(gate_invoking_account)
  if entry is None or entry.pw_uid < sa.system_uid__min():
    return [f"the asking account {clean(gate_invoking_account)} is not an account a person uses"]
  try:
    system_db = record.open__system()
  except record.RecordError as error:
    return [str(error)]
  try:
    list__problem = []
    for view in list__instruction_view:
      if view.operation == "enter":
        account_name = literal(view)[0]
        list__problem += [f"@{view.index} enter: {p}" for p in record.account__below(system_db ,gate_invoking_account ,account_name)]
    return list__problem
  finally:
    system_db.close()

def owned_file__problem(fpa__checked ,what ,uid ,is__kind ,kind):
  "None when fpa__checked is of the kind, owned by uid, and reached through no symbolic link"
  if os.path.realpath(fpa__checked) != fpa__checked:
    return f"{what} {fpa__checked} is reached through a symbolic link"
  try:
    st = os.lstat(fpa__checked)
  except OSError as error:
    return f"{what} {fpa__checked}: {error.strerror}"
  if not is__kind(st.st_mode):
    return f"{what} {fpa__checked} is not a {kind}"
  if st.st_uid != uid:
    return f"{what} {fpa__checked} is owned by uid {st.st_uid}, not by the asking account"
  return None

def check_filesystem(list__instruction_view ,data ,constraint ,gate_invoking_account):
  uid = pwd.getpwnam(gate_invoking_account).pw_uid
  dirpa__runtime = f"/run/user/{uid}/"
  list__problem = []
  for view in list__instruction_view:
    if view.operation != "enter":
      continue
    display = literal(view)[1]
    if display["wayland_display"]:
      if not display["wayland_display"].startswith(dirpa__runtime):
        list__problem.append(f"@{view.index} enter: Wayland socket {display['wayland_display']} is not in {dirpa__runtime}")
      else:
        problem = owned_file__problem(display["wayland_display"] ,"Wayland socket" ,uid ,stat.S_ISSOCK ,"socket")
        if problem: list__problem.append(f"@{view.index} enter: {problem}")
    if display["xauthority"]:
      problem = owned_file__problem(display["xauthority"] ,"X authority file" ,uid ,stat.S_ISREG ,"regular file")
      if problem: list__problem.append(f"@{view.index} enter: {problem}")
  return list__problem

LIST__CHECK = (
  ("language" ,check_language)
  ,("constraint" ,check_constraint)
  ,("record" ,check_record)
  ,("filesystem" ,check_filesystem)
)
