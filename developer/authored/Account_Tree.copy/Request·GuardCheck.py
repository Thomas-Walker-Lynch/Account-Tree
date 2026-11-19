# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Request·GuardCheck - the request guard's checks of the Request language.

Made after Man-In-Grey's well-formed guard has checked the journal against
the definition in Request·Language.py. They are LIST__CHECK:

  language     a journal holds one request, and its literals have the form
               their instruction takes: an account name, a display whose
               texts are empty or of the form each takes, a terminal type,
               a list of account names, none twice; an account to be made
               has a parent
  constraint   the predicates at the top of the guard, Request·Guard.py:
               is__allowed_account
  record       what the account tree allows, read from the system database
               and the storage databases: the asking account is an account
               a person uses, kept by Account-Tree; and for each request:
                 enter                the account is below it, active, and
                                      has its home mounted
                 make_child_account   the parent is the asking account or
                                      below it, and active; the name is free;
                                      the limits of the parent and of each
                                      account above it allow one more
                 deallocate           the account is below it, and every
                                      account below that one is deallocated
                 share_with           the sharing account and each member
                 share_remove         are the asking account or below it, on
                                      one storage, and no member is the
                                      sharing account
                 sound_show           the account is the asking account or
                                      below it, in a tree on its storage
                 sound_permit_issue   the login account of the tree issues
                 sound_permit_revoke  and revokes every permit in it;
                                      another account those of the
                                      accounts below it, for a permit it
                                      holds
                 sound_connection_set the account is the asking account or
                 sound_connection_reset below it and has a table; a new
                                      table's lines are well formed, name
                                      the tree's buses, and in the login
                                      account's table are device lines only
                 sound_bus_set        the asking account is the tree's login
                 sound_bus_remove     account; a bus removed is named in no
                                      connection table
                 sound_route_show     the asking account is in a tree
               see Request·Record.py and Sound.py
  filesystem   the display the request names is the asking account's, or
               one an account above it gave it: the Wayland socket is a
               socket in its owner's runtime directory, and the X authority
               file a regular file, each reached through no symbolic link,
               owned by the asking account or by an account above it in the
               tree, and usable by the asking account, which an account
               above it allows by entering it with its display. A display
               passed down the tree so gives a child no more than the asking
               account has

The gate's real uid, which the kernel gave it, names the asking account, so
nothing in a journal can say who asks.

The implementation of the requests is in Request·LibraryInstruction.py.
"""

import os ,pwd ,re ,stat

from Journal import has__control ,clean
from Common import SEPARATOR ,valid_name
import Request·Record as record
import Sound
import SystemAccount as sa

TEXT__CONNECTION__LENGTH_MAX = 65536

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
  elif view.operation == "make_child_account":
    account_name ,_ = literal(view)
    problem = valid_name(account_name) or (None if SEPARATOR in account_name else
              f"it has no parent but root; a login account is made by the administrator")
    if problem:
      list__problem.append(f"@{view.index} make_child_account: account {clean(repr(account_name))}: {problem}")
  elif view.operation == "deallocate":
    problem = valid_name(literal(view)[0])
    if problem:
      list__problem.append(f"@{view.index} deallocate: account {clean(repr(literal(view)[0]))}: {problem}")
  elif view.operation in ("share_with" ,"share_remove"):
    at = f"@{view.index} {view.operation}: "
    account_name ,list__member = literal(view)
    for name in [account_name] + list__member:
      problem = valid_name(name)
      if problem:
        list__problem.append(at + f"account {clean(repr(name))}: {problem}")
    if not list__member:
      list__problem.append(at + "no account to share with is given")
    if len(set(list__member)) != len(list__member):
      list__problem.append(at + "an account is given twice")
    if account_name in list__member:
      list__problem.append(at + f"{account_name} is given as sharing with itself")
  elif view.operation in ("sound_show" ,"sound_permit_issue" ,"sound_permit_revoke" ,"sound_connection_set" ,"sound_connection_reset"):
    at = f"@{view.index} {view.operation}: "
    value = literal(view)
    problem = valid_name(value[0])
    if problem:
      list__problem.append(at + f"account {clean(repr(value[0]))}: {problem}")
    if view.operation in ("sound_permit_issue" ,"sound_permit_revoke"):
      try:
        Sound.permit__parse(value[1])
      except ValueError as error:
        list__problem.append(at + clean(str(error)))
    if view.operation == "sound_connection_set":
      text = value[1]
      if len(text) > TEXT__CONNECTION__LENGTH_MAX:
        list__problem.append(at + f"the connection table is longer than {TEXT__CONNECTION__LENGTH_MAX} characters")
      if any(ord(c) < 0x20 and c not in "\n\t" for c in text):
        list__problem.append(at + "the connection table holds a control character")
  elif view.operation in ("sound_bus_set" ,"sound_bus_remove"):
    at = f"@{view.index} {view.operation}: "
    value = literal(view)
    if not 0 < value[0] <= Sound.BUS_NUMBER__MAX:
      list__problem.append(at + f"a bus number is from 1 to {Sound.BUS_NUMBER__MAX}")
    if view.operation == "sound_bus_set":
      problem = Sound.bus_name__problem(value[1])
      if problem:
        list__problem.append(at + f"bus name {clean(repr(value[1]))}: {problem}")
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
      at = f"@{view.index} {view.operation}: "
      value = literal(view)
      if view.operation == "enter":
        list__problem += [at + p for p in record.account__below(system_db ,gate_invoking_account ,value[0])]
      elif view.operation == "make_child_account":
        list__problem += [at + p for p in record.child_account__make__problem(system_db ,gate_invoking_account ,value[0])]
      elif view.operation == "deallocate":
        # deprecated: a state this version no longer makes, which an account can still be in
        found = record.account__below(system_db ,gate_invoking_account ,value[0] ,("active" ,"deprecated") ,is__mounted=False)
        if not found:
          try:
            below = record.below__not_in(system_db ,value[0] ,("deallocated",))
          except record.RecordError as error:
            below ,found = [] ,[str(error)]
          if below:
            found = [f"accounts below {value[0]} remain; deallocate them first: {', '.join(below)}"]
        list__problem += [at + p for p in found]
      elif view.operation in ("share_with" ,"share_remove"):
        account_name ,list__member = value
        if account_name != gate_invoking_account:
          list__problem += [at + p for p in record.account__below(system_db ,gate_invoking_account ,account_name
                                                                 ,("active",) ,is__mounted=False)]
        for member in list__member:
          if member == gate_invoking_account: continue
          list__problem += [at + p for p in record.account__below(system_db ,gate_invoking_account ,member
                                                                 ,("active",) ,is__mounted=False)]
      elif view.operation.startswith("sound_"):
        list__problem += [at + p for p in sound__problem(system_db ,gate_invoking_account ,view.operation ,value)]
    return list__problem
  finally:
    system_db.close()

def sound__problem(system_db ,asking ,operation ,value):
  """
  The problems the records find with a sound request by the system account
  asking; see Sound.py, whose checks the work functions make again under
  the lock.
  """
  try:
    storage_db ,account__asking = record.row__storage_account(system_db ,asking)
  except record.RecordError as error:
    return [str(error)]
  try:
    if Sound.login__of(storage_db ,account__asking) is None:
      return [f"{asking} is in no tree whose login account is on its storage"]
    if operation == "sound_route_show":
      return []
    if operation == "sound_bus_set":
      return Sound.bus_set__problem(storage_db ,account__asking ,value[0] ,value[1])
    if operation == "sound_bus_remove":
      return Sound.bus_remove__problem(system_db ,storage_db ,account__asking ,value[0])
    name = value[0]
    if name == asking:
      account = account__asking
    else:
      found = record.account__below(system_db ,asking ,name ,("active",) ,is__mounted=False)
      if found:
        return found
      row = record.system_map__in_use(system_db ,name)
      account = storage_db.execute("SELECT * FROM account WHERE database_uid = ?" ,(row["database_uid"],)).fetchone()
    if operation == "sound_show":
      return []
    if operation in ("sound_permit_issue" ,"sound_permit_revoke"):
      return Sound.permit_issue__problem(storage_db ,account__asking ,account ,value[1])
    if operation == "sound_connection_set":
      return Sound.connection_set__problem(storage_db ,account__asking ,account ,value[1])
    if operation == "sound_connection_reset":
      return Sound.connection_set__problem(storage_db ,account__asking ,account ,None)
    return [f"{operation} is not a sound request the guard knows"]
  finally:
    storage_db.close()

def is__usable(entry ,fpa__checked ,mode):
  """
  Whether the account of the pwd entry can open fpa__checked for mode, as
  os.access says when asked with that account's ids: the kernel applies the
  file's mode and ACL, as it would for that account. Asked in a child
  process, as the guard runs with root's rights.
  """
  pid = os.fork()
  if pid == 0:
    try:
      os.setgroups(os.getgrouplist(entry.pw_name ,entry.pw_gid))
      os.setresgid(entry.pw_gid ,entry.pw_gid ,entry.pw_gid)
      os.setresuid(entry.pw_uid ,entry.pw_uid ,entry.pw_uid)
      os._exit(0 if os.access(fpa__checked ,mode) else 1)
    except BaseException:
      os._exit(2)
  _ ,status = os.waitpid(pid ,0)
  return os.waitstatus_to_exitcode(status) == 0

def display_file__problem(system_db ,fpa__checked ,what ,asking ,is__kind ,kind ,mode):
  """
  None when fpa__checked is of the kind, reached through no symbolic link,
  owned by the asking account or by an account above it in the tree, and
  usable by the asking account for mode. Returns (problem ,owner): the pwd
  entry of the file's owner, None when the file cannot be read.
  """
  if os.path.realpath(fpa__checked) != fpa__checked:
    return f"{what} {fpa__checked} is reached through a symbolic link" ,None
  try:
    st = os.lstat(fpa__checked)
  except OSError as error:
    return f"{what} {fpa__checked}: {error.strerror}" ,None
  if not is__kind(st.st_mode):
    return f"{what} {fpa__checked} is not a {kind}" ,None
  try:
    owner = pwd.getpwuid(st.st_uid)
  except KeyError:
    return f"{what} {fpa__checked} is owned by uid {st.st_uid}, which no account has" ,None
  if owner.pw_uid != asking.pw_uid:
    found = record.account__below(system_db ,owner.pw_name ,asking.pw_name ,("active",) ,is__mounted=False)
    if found:
      return f"{what} {fpa__checked} is owned by {owner.pw_name}, neither the asking account nor one above it" ,owner
  if not is__usable(asking ,fpa__checked ,mode):
    return f"{what} {fpa__checked} is not usable by {asking.pw_name}; an account above it gives its display by entering it" ,owner
  return None ,owner

def check_filesystem(list__instruction_view ,data ,constraint ,gate_invoking_account):
  asking = pwd.getpwnam(gate_invoking_account)
  list__view = [view for view in list__instruction_view if view.operation == "enter"]
  if not list__view:
    return []
  try:
    system_db = record.open__system()
  except record.RecordError as error:
    return [str(error)]
  try:
    list__problem = []
    for view in list__view:
      at = f"@{view.index} enter: "
      display = literal(view)[1]
      if display["wayland_display"]:
        problem ,owner = display_file__problem(system_db ,display["wayland_display"] ,"Wayland socket" ,asking
                                               ,stat.S_ISSOCK ,"socket" ,os.R_OK | os.W_OK)
        if problem is None and not display["wayland_display"].startswith(f"/run/user/{owner.pw_uid}/"):
          problem = f"Wayland socket {display['wayland_display']} is not in its owner's runtime directory, /run/user/{owner.pw_uid}/"
        if problem: list__problem.append(at + problem)
      if display["xauthority"]:
        problem ,_ = display_file__problem(system_db ,display["xauthority"] ,"X authority file" ,asking
                                           ,stat.S_ISREG ,"regular file" ,os.R_OK)
        if problem: list__problem.append(at + problem)
    return list__problem
  finally:
    system_db.close()

LIST__CHECK = (
  ("language" ,check_language)
  ,("constraint" ,check_constraint)
  ,("record" ,check_record)
  ,("filesystem" ,check_filesystem)
)
