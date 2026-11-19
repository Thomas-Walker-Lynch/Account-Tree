# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Sound - the sound of an account tree: its buses, the permits to them, and
each account's connection table. See developer/design_audio.html.

The login account at the top of a tree is its hub. A bus is a summing node
in the hub, with a gather end and a broadcast end. An account connects
endpoints to bus ends: the streams of its programs, named by pattern, and,
for an account holding a device permit, the hub's chosen output or input,
@output and @input. What an account can connect is decided by its permits:

  allowance       the system's grant of sound to a login account, in the
                  system database's resource_allowance
  permit          set or not for one account and one bus end, as 1.gather,
                  or one device, as @output; in force when set and the
                  parent's same permit is in force, or, for the login
                  account, when the system has given the allowance
  mark            how a permit shows: blank, not set; gray, set and not in
                  force; full, set and in force

For each bus end an account other than the login account holds a full
permit for, there is a FIFO between it and the hub under
/run/Account-Tree/bus/<account>/. The routers, which carry out the tables
under each account, are not written yet; after a change this module tells
the routers concerned to reload, which does nothing where none runs.

Read functions take a storage database and a system database either as
Database.Database or as a read-only sqlite3 connection, so the request
guard and the work functions check with the same code. A table the guard
finds missing, in a database not opened for writing since this version,
is read as empty.

Work functions, run under root by the request interpreter or by
Account-Tree_admin, take the lock plug and unplug take, report through log,
and return False when they stop, having logged why:

  allowance__set     give or take a login account's allowance
  permit__set        set or clear a permit
  connection__set    replace an account's connection table
  connection__reset  put an account's default table back
  bus__set           make or rename a bus
  bus__remove        remove a bus no table names
  fifo__sync         make and delete a tree's FIFOs to match its records
  fifo__sync_storage the same for every tree of a storage, at attach
  fifo__remove       delete an account's FIFOs, at unplug and deallocation

Access functions return what they find:

  sound__of          what the window and the commands show of an account,
                     sound__show, asked by an account at or above it
  route__of          what an account's router needs, route__show
  list__allowance    the allowances the system has given
"""

import os ,re ,sqlite3 ,subprocess
from pathlib import Path

import Database
import StoragePlug
import SystemAccount as sa
from Common import act
from System import open_system_database


RESOURCE = "sound"
END__GATHER ,END__BROADCAST = "gather" ,"broadcast"
LIST__END = (END__GATHER ,END__BROADCAST)
LIST__DEVICE = ("@output" ,"@input")
MARK__BLANK ,MARK__GRAY ,MARK__FULL = "blank" ,"gray" ,"full"
KIND__PROGRAM ,KIND__DEVICE ,KIND__COMMENT = "program" ,"device" ,"comment"
BUS_NAME__LENGTH_MAX = 64
BUS_NUMBER__MAX = 999
DEPTH_MAX = 64
DIRPA__BUS = Path("/run/Account-Tree/bus")
UNIT__ROUTER = "Account-Tree_router.service"

LIST__BUS__DEFAULT = ((1 ,"system sound") ,(2 ,"system microphone"))

TEXT__CONNECTION__LOGIN = """\
broadcast  "system sound"       @output
gather     "system microphone"  @input
"""

TEXT__CONNECTION__CHILD = """\
# every program that plays is heard on system sound
gather     "system sound"       .*
# these programs hear the microphone
broadcast  "system microphone"  firefox|chromium|chrome|zoom
"""


class SoundError(Exception):
  """A sound record cannot be read."""


# --------------------------------------------------------------------------------
# reading, from a Database.Database or a read-only sqlite3 connection

def rows(db ,statement ,parameter=()):
  try:
    if hasattr(db ,"rows"):
      return db.rows(statement ,parameter)
    return db.execute(statement ,list(parameter)).fetchall()
  except sqlite3.OperationalError as error:
    if "no such table" in str(error):
      return []
    raise

def row(db ,statement ,parameter=()):
  found = rows(db ,statement ,parameter)
  return found[0] if found else None

def uuid__of(storage_db):
  return row(storage_db ,"SELECT database_uuid FROM identity")["database_uuid"]

def is__login(account):
  "whether a storage account is a login account: a child of root"
  return account["parent__database_uid"] is None and account["parent_name"] is None

def account__by_uid(storage_db ,database_uid):
  return row(storage_db ,"SELECT * FROM account WHERE database_uid = ?" ,(database_uid,))

def parent__of(storage_db ,account):
  if account["parent__database_uid"] is None:
    return None
  return account__by_uid(storage_db ,account["parent__database_uid"])

def login__of(storage_db ,account):
  "the login account at the top of account's tree, or None when the chain leaves the storage database"
  each = account
  for _ in range(DEPTH_MAX):
    if is__login(each):
      return each
    each = parent__of(storage_db ,each)
    if each is None:
      return None
  return None

def is__below(storage_db ,account ,account__above):
  "whether account is below account__above, by its storage database's parent links"
  each = account
  for _ in range(DEPTH_MAX):
    each = parent__of(storage_db ,each)
    if each is None:
      return False
    if each["database_uid"] == account__above["database_uid"]:
      return True
  return False

def system_name__of(system_db ,database_uuid ,account):
  "the system account name a storage account has on this system, in use or unplugged; its storage name otherwise"
  found = row(system_db ,"SELECT system_account__name FROM system_map WHERE database_uuid = ? AND database_uid = ?"
              " AND state IN ('in use' ,'unplugged') ORDER BY state LIMIT 1" ,(database_uuid ,account["database_uid"]))
  return found["system_account__name"] if found else account["name"]

def system_name__in_use(system_db ,database_uuid ,account):
  "the system account in use here for a storage account, or None"
  found = row(system_db ,"SELECT system_account__name FROM system_map WHERE database_uuid = ? AND database_uid = ?"
              " AND state = 'in use'" ,(database_uuid ,account["database_uid"]))
  return found["system_account__name"] if found else None

def list__tree(storage_db ,login):
  "the login account and every account below it that is not deallocated, in name order"
  return rows(storage_db
    ,"WITH RECURSIVE below(database_uid) AS ("
     " SELECT ? UNION SELECT a.database_uid FROM account a JOIN below b ON a.parent__database_uid = b.database_uid)"
     " SELECT * FROM account WHERE database_uid IN below AND state != 'deallocated' ORDER BY name"
    ,(login["database_uid"],))

def list__child(storage_db ,account):
  return rows(storage_db ,"SELECT * FROM account WHERE parent__database_uid = ? AND state != 'deallocated' ORDER BY name"
              ,(account["database_uid"],))

def is__allowance(system_db ,login_name):
  return row(system_db ,"SELECT 1 FROM resource_allowance WHERE resource = ? AND system_account__name = ?"
             ,(RESOURCE ,login_name)) is not None

def list__allowance(system_db):
  "every allowance this system has given, as rows of resource, system_account__name and given"
  return rows(system_db ,"SELECT * FROM resource_allowance ORDER BY resource ,system_account__name")

def is__configured(storage_db ,login):
  "whether sound is configured for login's tree: its defaults are made when its first permit is set"
  return has__table(storage_db ,login)

def has__table(storage_db ,account):
  return row(storage_db ,"SELECT 1 FROM sound_connection_table WHERE database_uid = ?" ,(account["database_uid"],)) is not None


# --------------------------------------------------------------------------------
# buses

def list__bus(storage_db ,login):
  """
  The buses of login's tree, as dictionaries of number and name; the
  default buses when sound is not configured for the tree yet, as setting
  its first permit makes them.
  """
  if not is__configured(storage_db ,login):
    return [{"number": n ,"name": name} for n ,name in LIST__BUS__DEFAULT]
  return [{"number": r["bus__number"] ,"name": r["name"]}
          for r in rows(storage_db ,"SELECT * FROM sound_bus WHERE login__database_uid = ? ORDER BY bus__number"
                        ,(login["database_uid"],))]

def bus__find(list__bus_ ,token):
  "the bus of list__bus_ that token names, by number or by name; None when none"
  for bus in list__bus_:
    if (token.isdigit() and bus["number"] == int(token)) or bus["name"] == token:
      return bus
  return None

def bus_name__problem(name):
  "why name cannot be a bus's name, or None"
  if not name or name != name.strip():
    return "a bus name is not empty and has no space at its ends"
  if len(name) > BUS_NAME__LENGTH_MAX:
    return f"a bus name is at most {BUS_NAME__LENGTH_MAX} characters"
  if any(ord(c) < 0x20 or ord(c) == 0x7F or c == '"' for c in name):
    return "a bus name holds no control character and no double quote"
  if name.isdigit():
    return "a bus name is not a number, since a bus is named by its number too"
  if name.startswith(("@" ,"#")):
    return "a bus name does not begin with @ or #"
  return None


# --------------------------------------------------------------------------------
# permits

def list__permit(list__bus_):
  "every permit of a tree with these buses, in the order the window shows them"
  return [f"{bus['number']}.{end}" for bus in list__bus_ for end in LIST__END] + list(LIST__DEVICE)

def permit__parse(text):
  """
  ("bus" ,number ,end) for a bus end permit, written <bus number>.<end>;
  ("device" ,None ,device) for a device permit, @output or @input. Raises
  ValueError.
  """
  if text in LIST__DEVICE:
    return ("device" ,None ,text)
  number ,dot ,end = text.partition(".")
  if dot and number.isdigit() and not number.startswith("0") and end in LIST__END:
    return ("bus" ,int(number) ,end)
  raise ValueError(f"the permit {text!r} is neither <bus number>.gather, <bus number>.broadcast, @output nor @input")

def is__permit_set(storage_db ,account ,permit):
  kind ,number ,name = permit__parse(permit)
  if kind == "device":
    return row(storage_db ,"SELECT 1 FROM sound_permit_device WHERE database_uid = ? AND device = ?"
               ,(account["database_uid"] ,name)) is not None
  return row(storage_db ,"SELECT 1 FROM sound_permit_bus_end WHERE database_uid = ? AND bus__number = ? AND bus_end = ?"
             ,(account["database_uid"] ,number ,name)) is not None

def is__in_force(system_db ,storage_db ,account ,permit ,login_name):
  "whether account's permit is set, and every same permit above it up to the login account, which the system allows sound"
  each = account
  for _ in range(DEPTH_MAX):
    if not is__permit_set(storage_db ,each ,permit):
      return False
    if is__login(each):
      return is__allowance(system_db ,login_name)
    each = parent__of(storage_db ,each)
    if each is None:
      return False
  return False

def mark__of(system_db ,storage_db ,account ,permit ,login_name):
  if not is__permit_set(storage_db ,account ,permit):
    return MARK__BLANK
  return MARK__FULL if is__in_force(system_db ,storage_db ,account ,permit ,login_name) else MARK__GRAY

def permit_set__problem(storage_db ,asking ,account ,permit):
  """
  The problems, as messages, with asking setting or clearing account's
  permit. The login account of the tree sets every permit in it, its own
  included; another account sets those of the accounts below it, for a
  permit it holds itself, gray or full.
  """
  try:
    kind ,number ,_ = permit__parse(permit)
  except ValueError as error:
    return [str(error)]
  login = login__of(storage_db ,account)
  if login is None:
    return [f"{account['name']} is in no tree whose login account is on its storage"]
  login__asking = login__of(storage_db ,asking)
  if login__asking is None or login__asking["database_uid"] != login["database_uid"]:
    return [f"{account['name']} is not in the tree of {asking['name']}"]
  list__problem = []
  if not is__login(asking):
    if account["database_uid"] == asking["database_uid"]:
      list__problem.append("an account's own permits are set by an account above it")
    elif not is__below(storage_db ,account ,asking):
      list__problem.append(f"{account['name']} is not below {asking['name']}")
    if not is__permit_set(storage_db ,asking ,permit):
      list__problem.append(f"{asking['name']} does not hold the permit {permit}, so it does not give it")
  if kind == "bus" and bus__find(list__bus(storage_db ,login) ,str(number)) is None:
    list__problem.append(f"the tree has no bus {number}")
  return list__problem


# --------------------------------------------------------------------------------
# connection tables

def split__word(text):
  "(the first word of text, the rest)"
  text = text.lstrip()
  i = 0
  while i < len(text) and not text[i].isspace():
    i += 1
  return text[:i] ,text[i:]

def line__parse(raw ,list__bus_ ,is__login_account):
  """
  (line ,problem) for one line of a connection table: line a dictionary of
  end, bus__number, endpoint__kind and endpoint, problem None or why the
  line cannot be taken. A blank line or one beginning with # is a comment.
  """
  text = raw.strip()
  if not text or text.startswith("#"):
    return {"end": None ,"bus__number": None ,"endpoint__kind": KIND__COMMENT ,"endpoint": text} ,None
  end ,rest = split__word(text)
  if end not in LIST__END:
    return None ,f"{end!r} is not an end; a line begins with gather or broadcast"
  rest = rest.lstrip()
  if rest.startswith('"'):
    close = rest.find('"' ,1)
    if close < 0:
      return None ,"the bus name's closing double quote is missing"
    token ,rest = rest[1:close] ,rest[close + 1:]
    if rest and not rest[0].isspace():
      return None ,"a quoted bus name is followed by a space"
  else:
    token ,rest = split__word(rest)
  if not token:
    return None ,"no bus is given"
  bus = bus__find(list__bus_ ,token)
  if bus is None:
    return None ,f"the tree has no bus {token!r}"
  endpoint = rest.strip()
  if not endpoint:
    return None ,"no endpoint is given: a program pattern, @output or @input"
  if any(ord(c) < 0x20 or ord(c) == 0x7F for c in endpoint):
    return None ,"the endpoint holds a control character"
  if endpoint.startswith("@"):
    if endpoint not in LIST__DEVICE:
      return None ,f"{endpoint!r} is not a device; the devices are {' and '.join(LIST__DEVICE)}"
    kind = KIND__DEVICE
  else:
    if is__login_account:
      return None ,"the login account's table holds device lines only, as its own programs are not to use sound"
    try:
      re.compile(endpoint)
    except re.error as error:
      return None ,f"the pattern {endpoint!r} is not a regular expression: {error}"
    kind = KIND__PROGRAM
  return {"end": end ,"bus__number": bus["number"] ,"endpoint__kind": kind ,"endpoint": endpoint} ,None

def connection__parse(text ,list__bus_ ,is__login_account):
  "(list__line ,list__problem) for a connection table's text; the problems name their lines"
  list__line ,list__problem = [] ,[]
  for number ,raw in enumerate(text.splitlines() ,1):
    line ,problem = line__parse(raw ,list__bus_ ,is__login_account)
    if problem:
      list__problem.append(f"line {number}: {problem}")
    else:
      list__line.append(line)
  return list__line ,list__problem

def connection__default(list__bus_ ,is__login_account):
  """
  The default lines for an account of the tree: the login account's or
  another account's. A default line naming a bus the tree no longer has is
  kept as a comment saying so.
  """
  list__line = []
  for raw in (TEXT__CONNECTION__LOGIN if is__login_account else TEXT__CONNECTION__CHILD).splitlines():
    line ,problem = line__parse(raw ,list__bus_ ,is__login_account)
    if problem:
      line = {"end": None ,"bus__number": None ,"endpoint__kind": KIND__COMMENT ,"endpoint": f"# {raw.strip()}    ({problem})"}
    list__line.append(line)
  return list__line

def list__line(storage_db ,account):
  "the lines of account's connection table, in order, as line__parse gives them"
  return [{"end": r["bus_end"] ,"bus__number": r["bus__number"] ,"endpoint__kind": r["endpoint__kind"] ,"endpoint": r["endpoint"]}
          for r in rows(storage_db ,"SELECT * FROM sound_connection WHERE database_uid = ? ORDER BY line__number"
                        ,(account["database_uid"],))]

def connection__text(list__line_ ,list__bus_):
  "a connection table's text, from its lines"
  map__name = {bus["number"]: bus["name"] for bus in list__bus_}
  list__text = []
  for line in list__line_:
    if line["endpoint__kind"] == KIND__COMMENT:
      list__text.append(line["endpoint"]); continue
    name = map__name.get(line["bus__number"] ,str(line["bus__number"]))
    bus = f'"{name}"' if any(c.isspace() for c in name) else name
    list__text.append(f"{line['end']:<10} {bus:<20} {line['endpoint']}")
  return "".join(t + "\n" for t in list__text)

def connection_set__problem(storage_db ,asking ,account ,text):
  "the problems with asking replacing account's connection table with text"
  login = login__of(storage_db ,account)
  if login is None:
    return [f"{account['name']} is in no tree whose login account is on its storage"]
  if account["database_uid"] != asking["database_uid"] and not is__below(storage_db ,account ,asking):
    return [f"{account['name']} is neither {asking['name']} nor below it"]
  if not has__table(storage_db ,account):
    return [f"{account['name']} has no connection table; it is made when its first permit is set"]
  if text is None:
    return []
  return connection__parse(text ,list__bus(storage_db ,login) ,is__login(account))[1]


def bus_set__problem(storage_db ,asking ,number ,name):
  "the problems with asking making or renaming bus number with the name"
  if not is__login(asking):
    return ["only the login account makes and renames its tree's buses"]
  if type(number) is not int or not 0 < number <= BUS_NUMBER__MAX:
    return [f"a bus number is from 1 to {BUS_NUMBER__MAX}"]
  problem = bus_name__problem(name)
  if problem:
    return [problem]
  # the default buses, when the tree has none yet, are the ones configure makes
  other = bus__find(list__bus(storage_db ,asking) ,name)
  if other is not None and other["number"] != number:
    return [f"bus {other['number']} is named {name} already"]
  return []

def bus_remove__problem(system_db ,storage_db ,asking ,number):
  "the problems with asking removing bus number"
  if not is__login(asking):
    return ["only the login account removes its tree's buses"]
  if not is__configured(storage_db ,asking) or bus__find(list__bus(storage_db ,asking) ,str(number)) is None:
    return [f"the tree has no bus {number}"]
  database_uuid = uuid__of(storage_db)
  list__naming = [system_name__of(system_db ,database_uuid ,a) for a in list__tree(storage_db ,asking)
                  if any(line["bus__number"] == number for line in list__line(storage_db ,a))]
  if list__naming:
    return [f"bus {number} is named in the connection tables of {', '.join(list__naming)}; move or delete those lines first"]
  return []


# --------------------------------------------------------------------------------
# what the window and the routers are told

def sound__show(system_db ,storage_db ,account):
  """
  What the window and the commands show of account: a dictionary in the
  form of the request language's sound type.
  """
  login = login__of(storage_db ,account)
  database_uuid = uuid__of(storage_db)
  login_name = system_name__of(system_db ,database_uuid ,login)
  list__bus_ = list__bus(storage_db ,login)
  list__permit_ = list__permit(list__bus_)
  list__tree_ = list__tree(storage_db ,login)
  def holder(permit):
    return [system_name__of(system_db ,database_uuid ,a) for a in list__tree_ if is__permit_set(storage_db ,a ,permit)]
  list__show = [account] + list__child(storage_db ,account)
  return {
    "login": login_name
    ,"is__allowance": is__allowance(system_db ,login_name)
    ,"is__configured": is__configured(storage_db ,login)
    ,"list__bus": [{"number": bus["number"] ,"name": bus["name"]
                    ,"list__gather": holder(f"{bus['number']}.gather")
                    ,"list__broadcast": holder(f"{bus['number']}.broadcast")} for bus in list__bus_]
    ,"list__device": [{"device": d ,"list__holder": holder(d)} for d in LIST__DEVICE]
    ,"list__row": [{"name": system_name__of(system_db ,database_uuid ,a)
                    ,"list__mark": [{"permit": p ,"mark": mark__of(system_db ,storage_db ,a ,p ,login_name)} for p in list__permit_]}
                   for a in list__show]
    ,"has__table": has__table(storage_db ,account)
    ,"connection": connection__text(list__line(storage_db ,account) ,list__bus_)
  }

def fifo__path(system_account__name ,bus__number ,end):
  return DIRPA__BUS / system_account__name / f"{bus__number}.{end}"

def fifo__desired(system_db ,storage_db ,login):
  """
  The FIFOs login's tree is to have: path -> (system account ,bus number
  ,end), for each bus end an account in use here, other than the login
  account, holds a full permit for.
  """
  database_uuid = uuid__of(storage_db)
  login_name = system_name__of(system_db ,database_uuid ,login)
  if not is__configured(storage_db ,login) or not is__allowance(system_db ,login_name):
    return {}
  result = {}
  list__bus_ = list__bus(storage_db ,login)
  for account in list__tree(storage_db ,login):
    if is__login(account): continue
    name = system_name__in_use(system_db ,database_uuid ,account)
    if name is None: continue
    for bus in list__bus_:
      for end in LIST__END:
        if is__in_force(system_db ,storage_db ,account ,f"{bus['number']}.{end}" ,login_name):
          result[fifo__path(name ,bus["number"] ,end)] = (name ,bus["number"] ,end)
  return result

def route__show(system_db ,storage_db ,account):
  """
  What account's router needs, a dictionary in the form of the request
  language's route type. Another account's router is given its program
  lines in force and its FIFOs; the hub's, the login account's, is given
  every FIFO of the tree and the device connections in force, one for each
  distinct device and bus end, however many tables name it.
  """
  login = login__of(storage_db ,account)
  database_uuid = uuid__of(storage_db)
  login_name = system_name__of(system_db ,database_uuid ,login)
  list__bus_ = list__bus(storage_db ,login) if is__configured(storage_db ,login) else []
  is__hub = is__login(account)
  name = system_name__of(system_db ,database_uuid ,account)
  def in_force(a ,permit):
    return is__in_force(system_db ,storage_db ,a ,permit ,login_name)
  list__line_ = []
  list__device = []
  if is__hub:
    set__seen = set()
    for a in list__tree(storage_db ,login):
      if not is__login(a) and system_name__in_use(system_db ,database_uuid ,a) is None: continue
      for line in list__line(storage_db ,a):
        if line["endpoint__kind"] != KIND__DEVICE: continue
        key = (line["endpoint"] ,line["bus__number"] ,line["end"])
        if key in set__seen: continue
        if in_force(a ,line["endpoint"]) and in_force(a ,f"{line['bus__number']}.{line['end']}"):
          set__seen.add(key)
          list__device.append({"device": key[0] ,"bus__number": key[1] ,"end": key[2]})
    list__fifo = [{"account": n ,"bus__number": b ,"end": e ,"path": str(p)}
                  for p ,(n ,b ,e) in sorted(fifo__desired(system_db ,storage_db ,login).items())]
  else:
    for line in list__line(storage_db ,account):
      if line["endpoint__kind"] == KIND__PROGRAM and in_force(account ,f"{line['bus__number']}.{line['end']}"):
        list__line_.append({"end": line["end"] ,"bus__number": line["bus__number"] ,"pattern": line["endpoint"]})
    list__fifo = [{"account": n ,"bus__number": b ,"end": e ,"path": str(p)}
                  for p ,(n ,b ,e) in sorted(fifo__desired(system_db ,storage_db ,login).items()) if n == name]
  return {
    "is__hub": is__hub
    ,"list__bus": [{"number": bus["number"] ,"name": bus["name"]} for bus in list__bus_]
    ,"list__line": list__line_
    ,"list__fifo": list__fifo
    ,"list__device": list__device
  }


# --------------------------------------------------------------------------------
# changing: the records

def found__tree(name ,log):
  """
  (system_db ,storage_db ,account ,login ,login_name) for a system account
  Account-Tree keeps in use here, its storage database opened for writing;
  None with an error logged.
  """
  import ChildAccount   # here, as ChildAccount imports this module
  found = ChildAccount.account__in_use(name ,log)
  if found is None: return None
  system_db ,_ ,_ ,storage_db ,account = found
  login = login__of(storage_db ,account)
  if login is None:
    log.error(name ,"its tree's login account is not on its storage, and sound is configured from a login account"); return None
  return system_db ,storage_db ,account ,login ,system_name__of(system_db ,storage_db.uuid() ,login)

def found__asking(asking ,storage_db ,login ,log):
  "the storage account of the asking system account, in login's tree on storage_db; None with an error logged"
  import ChildAccount
  found = ChildAccount.account__in_use(asking ,log)
  if found is None: return None
  _ ,row__asking ,_ ,_ ,account = found
  if row__asking["database_uuid"] != storage_db.uuid():
    log.error(asking ,"is kept on another storage"); return None
  login__asking = login__of(storage_db ,account)
  if login__asking is None or login__asking["database_uid"] != login["database_uid"]:
    log.error(asking ,"is not in the same tree"); return None
  return account

def sound__of(asking ,name ,log):
  """
  sound__show for name, asked by the system account asking, which is name
  or above it; None with an error logged.
  """
  found = found__tree(name ,log)
  if found is None: return None
  system_db ,storage_db ,account ,login ,_ = found
  account__asking = found__asking(asking ,storage_db ,login ,log)
  if account__asking is None: return None
  if account["database_uid"] != account__asking["database_uid"] and not is__below(storage_db ,account ,account__asking):
    log.error(name ,f"is neither {asking} nor below it"); return None
  return sound__show(system_db ,storage_db ,account)

def route__of(asking ,log):
  "route__show for the system account asking, for its router; None with an error logged"
  found = found__tree(asking ,log)
  if found is None: return None
  system_db ,storage_db ,account ,_ ,_ = found
  return route__show(system_db ,storage_db ,account)

def configure(t ,login):
  "within the transaction t, make the defaults of login's tree: its buses, the login account's permits and its table"
  stamp = Database.now()
  for number ,name in LIST__BUS__DEFAULT:
    t.execute("INSERT INTO sound_bus(login__database_uid ,bus__number ,name ,made) VALUES (? ,? ,? ,?)"
              ,(login["database_uid"] ,number ,name ,stamp))
    for end in LIST__END:
      t.execute("INSERT INTO sound_permit_bus_end(database_uid ,bus__number ,bus_end ,made) VALUES (? ,? ,? ,?)"
                ,(login["database_uid"] ,number ,end ,stamp))
  for device in LIST__DEVICE:
    t.execute("INSERT INTO sound_permit_device(database_uid ,device ,made) VALUES (? ,? ,?)"
              ,(login["database_uid"] ,device ,stamp))
  list__bus_ = [{"number": n ,"name": name} for n ,name in LIST__BUS__DEFAULT]
  table__write(t ,login ,connection__default(list__bus_ ,True) ,is__new=True)

def table__write(t ,account ,list__line_ ,is__new=False):
  "within the transaction t, make account's table, or replace its lines"
  if is__new:
    t.execute("INSERT INTO sound_connection_table(database_uid ,made) VALUES (? ,?)" ,(account["database_uid"] ,Database.now()))
  t.execute("DELETE FROM sound_connection WHERE database_uid = ?" ,(account["database_uid"],))
  for number ,line in enumerate(list__line_ ,1):
    t.execute("INSERT INTO sound_connection(database_uid ,line__number ,bus_end ,bus__number ,endpoint__kind ,endpoint)"
              " VALUES (? ,? ,? ,? ,? ,?)"
              ,(account["database_uid"] ,number ,line["end"] ,line["bus__number"] ,line["endpoint__kind"] ,line["endpoint"]))

def allowance__set(login_name ,is__given ,log ,preview):
  """
  Give or take the allowance of sound to the login account login_name.
  Giving it to a tree sound is not configured for makes the tree's
  defaults. Returns True when it was done, or would be.
  """
  with StoragePlug.Lock():
    system_db = open_system_database(log)
    if system_db is None: return False
    r = system_db.row("SELECT * FROM system_map WHERE system_account__name = ? AND state IN ('in use' ,'unplugged')"
                      " ORDER BY state LIMIT 1" ,(login_name,))
    if r is None:
      log.error(login_name ,"not an account Account-Tree keeps on this system"); return False
    found = None
    if r["state"] == "in use":
      found = found__tree(login_name ,log)
      if found is None: return False
      _ ,storage_db ,account ,login ,_ = found
      if not is__login(account):
        log.error(login_name ,"a child account; the system gives sound to login accounts only"); return False
    if is__allowance(system_db ,login_name) == is__given:
      log.line("kept" ,login_name ,f"sound already {'given' if is__given else 'not given'}")
    else:
      with system_db.transaction(f"{'give' if is__given else 'take'} sound {'to' if is__given else 'from'} {login_name}" ,preview) as t:
        if is__given:
          t.execute("INSERT INTO resource_allowance(resource ,system_account__name ,given) VALUES (? ,? ,?)"
                    ,(RESOURCE ,login_name ,Database.now()))
        else:
          t.execute("DELETE FROM resource_allowance WHERE resource = ? AND system_account__name = ?" ,(RESOURCE ,login_name))
      log.line("given" if is__given else "taken" ,login_name ,"the allowance of sound")
    if found is None:
      log.line("kept" ,login_name ,"its storage is unplugged; its tree comes up for sound when it is plugged in")
      return True
    if is__given and not is__configured(storage_db ,login):
      with storage_db.transaction(f"configure sound for the tree of {login_name}" ,preview) as t:
        configure(t ,login)
      log.line("made" ,f"the sound of {login_name}'s tree" ,"its default buses, its permits and its table")
    return fifo__sync(system_db ,storage_db ,login ,log ,preview)

def permit__set(asking ,name ,permit ,is__set ,log ,preview):
  """
  Set or clear name's permit, asked by the system account asking. The first
  permit set in a tree makes the tree's defaults; the first set for an
  account makes its connection table. Returns True when it was done, or
  would be.
  """
  with StoragePlug.Lock():
    found = found__tree(name ,log)
    if found is None: return False
    system_db ,storage_db ,account ,login ,login_name = found
    account__asking = found__asking(asking ,storage_db ,login ,log)
    if account__asking is None: return False
    list__problem = permit_set__problem(storage_db ,account__asking ,account ,permit)
    if list__problem:
      for p in list__problem: log.error(name ,p)
      return False
    kind ,number ,which = permit__parse(permit)
    with storage_db.transaction(f"{'set' if is__set else 'clear'} the sound permit {permit} of {name}" ,preview) as t:
      if not is__configured(storage_db ,login):
        configure(t ,login)
        log.line("made" ,f"the sound of {login_name}'s tree" ,"its default buses, its permits and its table")
      is__now = is__permit_set(storage_db ,account ,permit)
      if is__now == is__set:
        log.line("kept" ,f"{name} {permit}" ,f"already {'set' if is__set else 'clear'}")
      elif is__set:
        if kind == "device":
          t.execute("INSERT INTO sound_permit_device(database_uid ,device ,made) VALUES (? ,? ,?)"
                    ,(account["database_uid"] ,which ,Database.now()))
        else:
          t.execute("INSERT INTO sound_permit_bus_end(database_uid ,bus__number ,bus_end ,made) VALUES (? ,? ,? ,?)"
                    ,(account["database_uid"] ,number ,which ,Database.now()))
        log.line("set" ,f"{name} {permit}")
      else:
        if kind == "device":
          t.execute("DELETE FROM sound_permit_device WHERE database_uid = ? AND device = ?" ,(account["database_uid"] ,which))
        else:
          t.execute("DELETE FROM sound_permit_bus_end WHERE database_uid = ? AND bus__number = ? AND bus_end = ?"
                    ,(account["database_uid"] ,number ,which))
        log.line("cleared" ,f"{name} {permit}")
      if is__set and not has__table(storage_db ,account):
        table__write(t ,account ,connection__default(list__bus(storage_db ,login) ,is__login(account)) ,is__new=True)
        log.line("made" ,f"the connection table of {name}" ,"from the default lines")
    return fifo__sync(system_db ,storage_db ,login ,log ,preview)

def connection__set(asking ,name ,text ,log ,preview):
  """
  Replace name's connection table with the lines of text, asked by the
  system account asking; text None puts the default lines back. Returns True
  when it was done, or would be.
  """
  with StoragePlug.Lock():
    found = found__tree(name ,log)
    if found is None: return False
    system_db ,storage_db ,account ,login ,login_name = found
    account__asking = found__asking(asking ,storage_db ,login ,log)
    if account__asking is None: return False
    list__problem = connection_set__problem(storage_db ,account__asking ,account ,text)
    if list__problem:
      for p in list__problem: log.error(name ,p)
      return False
    list__bus_ = list__bus(storage_db ,login)
    if text is None:
      list__line_ = connection__default(list__bus_ ,is__login(account))
    else:
      list__line_ ,_ = connection__parse(text ,list__bus_ ,is__login(account))
    with storage_db.transaction(f"{'reset' if text is None else 'set'} the connection table of {name}" ,preview) as t:
      table__write(t ,account ,list__line_)
    count = sum(1 for line in list__line_ if line["endpoint__kind"] != KIND__COMMENT)
    log.line("set" ,f"the connection table of {name}" ,f"{count} connection lines{', the default' if text is None else ''}")
    router__reload(system_name__of(system_db ,storage_db.uuid() ,account) ,log ,preview)
    if not is__login(account):
      router__reload(login_name ,log ,preview)
    return True

def connection__reset(asking ,name ,log ,preview):
  return connection__set(asking ,name ,None ,log ,preview)

def bus__set(asking ,number ,name ,log ,preview):
  """
  Make the bus number with the name, or rename it, in asking's tree; asking
  is its login account. Returns True when it was done, or would be.
  """
  with StoragePlug.Lock():
    found = found__tree(asking ,log)
    if found is None: return False
    system_db ,storage_db ,account ,login ,login_name = found
    list__problem = bus_set__problem(storage_db ,account ,number ,name)
    if list__problem:
      for p in list__problem: log.error(f"bus {number}" ,p)
      return False
    now = bus__find(list__bus(storage_db ,login) ,str(number))
    with storage_db.transaction(f"set bus {number} of {login_name}'s tree, named {name}" ,preview) as t:
      if not is__configured(storage_db ,login):
        configure(t ,login)
        log.line("made" ,f"the sound of {login_name}'s tree" ,"its default buses, its permits and its table")
      if now is None:
        t.execute("INSERT INTO sound_bus(login__database_uid ,bus__number ,name ,made) VALUES (? ,? ,? ,?)"
                  ,(login["database_uid"] ,number ,name ,Database.now()))
        # the login account holds every permit by default, so it can pass them down
        for end in LIST__END:
          t.execute("INSERT INTO sound_permit_bus_end(database_uid ,bus__number ,bus_end ,made) VALUES (? ,? ,? ,?)"
                    ,(login["database_uid"] ,number ,end ,Database.now()))
        log.line("made" ,f"bus {number}" ,f"{name}, with the login account's permits for its ends")
      elif now["name"] != name:
        t.execute("UPDATE sound_bus SET name = ? WHERE login__database_uid = ? AND bus__number = ?"
                  ,(name ,login["database_uid"] ,number))
        log.line("renamed" ,f"bus {number}" ,f"from {now['name']} to {name}")
      else:
        log.line("kept" ,f"bus {number}" ,f"already named {name}")
    return fifo__sync(system_db ,storage_db ,login ,log ,preview ,is__reload_all=True)

def bus__remove(asking ,number ,log ,preview):
  """
  Remove the bus number from asking's tree, and every permit for its ends;
  refused while a connection table names it. Returns True when it was done,
  or would be.
  """
  with StoragePlug.Lock():
    found = found__tree(asking ,log)
    if found is None: return False
    system_db ,storage_db ,account ,login ,login_name = found
    list__problem = bus_remove__problem(system_db ,storage_db ,account ,number)
    if list__problem:
      for p in list__problem: log.error(f"bus {number}" ,p)
      return False
    with storage_db.transaction(f"remove bus {number} of {login_name}'s tree" ,preview) as t:
      for a in list__tree(storage_db ,login):
        t.execute("DELETE FROM sound_permit_bus_end WHERE database_uid = ? AND bus__number = ?" ,(a["database_uid"] ,number))
      t.execute("DELETE FROM sound_bus WHERE login__database_uid = ? AND bus__number = ?" ,(login["database_uid"] ,number))
    log.line("removed" ,f"bus {number}" ,"with the permits for its ends")
    return fifo__sync(system_db ,storage_db ,login ,log ,preview ,is__reload_all=True)

def account__forget(t ,account):
  "within the transaction t, delete an account's sound rows, as deallocation does"
  for table in ("sound_permit_bus_end" ,"sound_permit_device" ,"sound_connection" ,"sound_connection_table"):
    t.execute(f"DELETE FROM {table} WHERE database_uid = ?" ,(account["database_uid"],))


# --------------------------------------------------------------------------------
# changing: the FIFOs and the routers

def router__reload(system_account__name ,log ,preview):
  """
  Tell the router running under the account to reload, so it asks again for
  what it is to do. Nothing is done when the account has no systemd user
  instance, or no router.
  """
  entry = sa.system_account(system_account__name)
  if entry is None or not Path(f"/run/user/{entry.pw_uid}/systemd/private").exists():
    return
  if preview:
    log.line("reload" ,f"{UNIT__ROUTER} of {system_account__name}"); return
  done = subprocess.run(["systemctl" ,"--user" ,f"--machine={system_account__name}@" ,"reload" ,UNIT__ROUTER]
                        ,stdin=subprocess.DEVNULL ,stdout=subprocess.DEVNULL ,stderr=subprocess.DEVNULL)
  if done.returncode == 0:
    log.line("reloaded" ,f"{UNIT__ROUTER} of {system_account__name}")

def directory__make(dirpa__account):
  """
  Make each directory down to an account's FIFOs, or give it its mode: each
  is root's, mode 0711, so an account passes through to its FIFO by name
  and lists nothing.
  """
  for dirpa in (DIRPA__BUS.parent ,DIRPA__BUS ,dirpa__account):
    if not dirpa.is_dir():
      os.mkdir(dirpa ,0o711)
    if os.stat(dirpa).st_mode & 0o7777 != 0o711:
      os.chmod(dirpa ,0o711)

def fifo__make(path ,owner ,login_name ,end ,log ,preview):
  """
  Make the FIFO at path between the account owner and the hub, login_name:
  the account writes it and the hub reads it for a gather end, the other way
  for a broadcast end. The FIFO is the account's, with the hub's access
  through an ACL entry, so no group, and no account a share makes a member
  of one, opens it.
  """
  entry__owner = sa.system_account(owner)
  entry__login = sa.system_account(login_name)
  if entry__owner is None or entry__login is None:
    log.error(str(path) ,f"{owner if entry__owner is None else login_name} has no system account here"); return False
  mode__owner ,access__login = (0o200 ,"r") if end == END__GATHER else (0o400 ,"w")
  def make():
    directory__make(path.parent)
    os.mkfifo(path ,0)
    os.chown(path ,entry__owner.pw_uid ,0)
    os.chmod(path ,mode__owner)
    subprocess.run(["setfacl" ,"-m" ,f"u:{entry__login.pw_uid}:{access__login}" ,str(path)] ,check=True
                   ,stdin=subprocess.DEVNULL ,stdout=subprocess.DEVNULL)
  if not act(log ,preview ,str(path) ,make): return False
  log.line("made" ,str(path) ,f"{owner} {'writes' if end == END__GATHER else 'reads'} it, {login_name} {'reads' if end == END__GATHER else 'writes'} it")
  return True

def is__fifo_current(path ,owner ,login_name ,end):
  """
  Whether the FIFO at path is the one fifo__make makes for owner and the hub
  login_name now: a FIFO owned by owner's system uid, with the ACL entry for
  login_name's. A system uid changes when a storage is plugged in again.
  """
  import stat
  entry__owner ,entry__login = sa.system_account(owner) ,sa.system_account(login_name)
  if entry__owner is None or entry__login is None:
    return False
  try:
    st = os.lstat(path)
  except OSError:
    return False
  if not stat.S_ISFIFO(st.st_mode) or st.st_uid != entry__owner.pw_uid:
    return False
  access = "r--" if end == END__GATHER else "-w-"
  done = subprocess.run(["getfacl" ,"--numeric" ,"--omit-header" ,str(path)] ,capture_output=True ,text=True)
  return done.returncode == 0 and f"user:{entry__login.pw_uid}:{access}" in done.stdout.split()

def fifo__remove__path(path ,log ,preview):
  if not act(log ,preview ,str(path) ,os.unlink ,path): return False
  log.line("deleted" ,str(path))
  return True

def fifo__sync(system_db ,storage_db ,login ,log ,preview ,is__reload_all=False):
  """
  Make and delete the FIFOs of login's tree so they match its records, and
  tell the routers whose FIFOs changed to reload, and the hub's; with
  is__reload_all, every router in the tree. Returns False when a FIFO could
  not be made or deleted.
  """
  database_uuid = storage_db.uuid()
  login_name = system_name__of(system_db ,database_uuid ,login)
  desired = fifo__desired(system_db ,storage_db ,login)
  list__name = [n for n in (system_name__in_use(system_db ,database_uuid ,a) for a in list__tree(storage_db ,login)
                            if not is__login(a)) if n is not None]
  is__done = True
  set__changed = set()
  for name in list__name:
    dirpa = DIRPA__BUS / name
    if not dirpa.is_dir(): continue
    for path in sorted(dirpa.iterdir()):
      if path not in desired:
        is__done = fifo__remove__path(path ,log ,preview) and is__done
        set__changed.add(name)
  for path ,(name ,_ ,end) in sorted(desired.items()):
    if path.exists() or path.is_symlink():
      if is__fifo_current(path ,name ,login_name ,end):
        if not preview: directory__make(path.parent)
        continue
      if not fifo__remove__path(path ,log ,preview):
        is__done = False; continue
    is__done = fifo__make(path ,name ,login_name ,end ,log ,preview) and is__done
    set__changed.add(name)
  for name in list__name:
    dirpa = DIRPA__BUS / name
    if dirpa.is_dir() and not preview and not any(dirpa.iterdir()):
      os.rmdir(dirpa)
  for name in (list__name if is__reload_all else sorted(set__changed)):
    router__reload(name ,log ,preview)
  router__reload(login_name ,log ,preview)
  return is__done

def fifo__sync_storage(system_db ,storage_db ,log ,preview):
  "fifo__sync for every tree of the storage sound is configured for, as attach makes its accounts"
  for login in rows(storage_db ,"SELECT * FROM account WHERE parent__database_uid IS NULL AND parent_name IS NULL"
                    " AND state != 'deallocated' ORDER BY name"):
    if is__configured(storage_db ,login):
      fifo__sync(system_db ,storage_db ,login ,log ,preview)

def fifo__remove(system_account__name ,log ,preview):
  "delete the FIFOs of the system account, and their directory, before its system account goes"
  dirpa = DIRPA__BUS / system_account__name
  if not dirpa.is_dir(): return True
  is__done = True
  for path in sorted(dirpa.iterdir()):
    is__done = fifo__remove__path(path ,log ,preview) and is__done
  if is__done and not preview:
    os.rmdir(dirpa)
  return is__done
