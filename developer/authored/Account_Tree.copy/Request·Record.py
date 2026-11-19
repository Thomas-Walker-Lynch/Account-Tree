# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Request·Record - what the request guard reads of the account tree, from the
system database and the storage databases, opened read-only.

The guard decides from the records, never from names: an account is below
another when the parent links of its storage database lead up to it. The
databases are opened with SQLite's mode=ro, so the guard can change nothing,
and nothing the schema adds on opening, as Database.Database.open does, runs.

  RecordError                  a record cannot be read
  open__read_only              a database, read-only
  system_map__in_use           the system map row of a system account in use
  storage_database__of         the storage database of a database uuid, read-only,
                               found where it is mounted
  is__below                    whether one storage account is below another,
                               and why not
  account__below               the checks the request guard makes of an account
                               a request names, below the asking account
  child_account__make__problem the checks of a request to make an account: its
                               parent is the asking account or below it, its
                               name is free, and the limits allow one more
  below__not_in                the accounts below an account not in given states

A limit, set by the administrator with limit set, says how many accounts can
be below an account, counted in its storage database, those deallocated left
out. Making an account needs room under the limit of its parent and of each
account above it up to the login account. An account with no
limit set can have System.LIMIT__DEFAULT below it.
"""

import os ,pwd ,sqlite3
from pathlib import Path

import Database
import Kernel
from Common import DIRPA__HOME ,SEPARATOR ,dirpa__Account_Tree ,valid_name
import SystemAccount as sa
from System import limit__of

DEPTH_MAX = 64   # no tree is deeper; a longer chain of parent links is a loop


class RecordError(Exception):
  """A record cannot be read."""


def open__read_only(filep__database):
  """
  The database at filep__database opened read-only, its rows as
  sqlite3.Row. Raises RecordError.
  """
  filep__database = Path(filep__database)
  if not filep__database.is_file():
    raise RecordError(f"no database at {filep__database}")
  try:
    connection = sqlite3.connect(filep__database.resolve().as_uri() + "?mode=ro" ,uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("SELECT 1 FROM identity").fetchone()
  except sqlite3.Error as error:
    raise RecordError(f"{filep__database}: {error}")
  return connection

def open__system():
  return open__read_only(Database.FPA__SYSTEM_DATABASE)

def system_map__in_use(system_db ,system_account__name):
  "the system map row in use for the system account, or None"
  return system_db.execute("SELECT * FROM system_map WHERE system_account__name = ? AND state = 'in use'"
                           ,(system_account__name,)).fetchone()

def storage_database__of(system_db ,database_uuid):
  """
  The storage database whose database uuid is database_uuid, read-only, and
  the root of the storage it is on. It is looked for at the mount point of
  each registered removable storage carrying it, and at /, the disk the
  system runs from. Raises RecordError when it is in none of them.
  """
  list__dirpa__root = [Path(r["dirpa__mount"]) for r in system_db.execute(
    "SELECT dirpa__mount FROM storage_device WHERE database_uuid = ? AND state = 'registered'" ,(database_uuid,))]
  list__dirpa__root.append(Path("/"))
  for dirpa__root in list__dirpa__root:
    if dirpa__root != Path("/") and not Kernel.is__mount_point(dirpa__root):
      continue
    filep__database = Database.fpa__storage_database(dirpa__Account_Tree(dirpa__root))
    if not filep__database.is_file():
      continue
    storage_db = open__read_only(filep__database)
    row = storage_db.execute("SELECT database_uuid FROM identity").fetchone()
    if row is not None and row["database_uuid"] == database_uuid:
      return storage_db ,dirpa__root
    storage_db.close()
  raise RecordError(f"the storage database {database_uuid} is not found on any storage attached here")

def is__below(storage_db ,database_uid ,database_uid__above):
  """
  (True ,None) when the storage account database_uid is below the storage
  account database_uid__above in storage_db, by the parent links of the
  database; otherwise (False ,why). An account is not below itself. A chain
  that leaves the database, a parent named but not carried here, is not
  followed: in this version a request reaches only accounts whose parents
  are all carried by one storage database.
  """
  each = database_uid
  for _ in range(DEPTH_MAX):
    row = storage_db.execute("SELECT * FROM account WHERE database_uid = ?" ,(each,)).fetchone()
    if row is None:
      return False ,f"the storage database has no account of database uid {each}"
    parent = row["parent__database_uid"]
    if parent is None:
      if row["parent_name"] is None:
        return False ,f"{row['name']} is a child of root, and the chain above it does not pass the asking account"
      return False ,(f"the parent of {row['name']}, {row['parent_name']}, is kept on another storage;"
                     " a request reaches only accounts whose parents are on the same storage")
    if parent == database_uid__above:
      return True ,None
    each = parent
  return False ,f"the parent links above database uid {database_uid} are longer than {DEPTH_MAX}, a loop"

def account__below(system_db ,account__asking ,account__named ,list__state=("active",) ,is__mounted=True):
  """
  The problems, as a list of messages, with a request by the system account
  account__asking that names the system account account__named. Empty when
  account__named is below account__asking in the tree, both are managed by
  Account-Tree and in use here, the named one is in one of the states in
  list__state, the system map agrees with /etc/passwd about its uid, and,
  with is__mounted, its home is mounted.
  """
  if account__named == account__asking:
    return [f"{account__named} is the asking account itself, not an account below it"]
  row__asking = system_map__in_use(system_db ,account__asking)
  if row__asking is None:
    return [f"the asking account {account__asking} is not an account Account-Tree keeps in use here"]
  row__named = system_map__in_use(system_db ,account__named)
  if row__named is None:
    return [f"{account__named} is not an account Account-Tree keeps in use here"]
  if row__named["database_uuid"] != row__asking["database_uuid"]:
    return [f"{account__named} is kept on another storage than {account__asking};"
            " a request reaches only accounts on the asking account's storage"]
  entry = sa.system_account(account__named)
  if entry is None or entry.pw_uid != row__named["system_uid"]:
    return [f"the system map gives {account__named} the system uid {row__named['system_uid']}, and /etc/passwd does not"]
  try:
    storage_db ,_ = storage_database__of(system_db ,row__named["database_uuid"])
  except RecordError as error:
    return [str(error)]
  try:
    state = storage_db.execute("SELECT state FROM account WHERE database_uid = ?" ,(row__named["database_uid"],)).fetchone()
    if state is None or state["state"] not in list__state:
      return [f"{account__named} is {state['state'] if state else 'not'} in its storage database, not {' or '.join(list__state)}"]
    below ,why = is__below(storage_db ,row__named["database_uid"] ,row__asking["database_uid"])
    if not below:
      return [f"{account__named} is not below {account__asking}: {why}"]
  finally:
    storage_db.close()
  if is__mounted and not Kernel.is__mount_point(DIRPA__HOME / account__named):
    return [f"the home of {account__named}, {DIRPA__HOME / account__named}, is not mounted"]
  return []

def row__storage_account(system_db ,system_account__name):
  """
  (storage_db ,account) for a system account in use here: its storage
  database, read-only, and its row there. Raises RecordError.
  """
  row = system_map__in_use(system_db ,system_account__name)
  if row is None:
    raise RecordError(f"{system_account__name} is not an account Account-Tree keeps in use here")
  storage_db ,_ = storage_database__of(system_db ,row["database_uuid"])
  account = storage_db.execute("SELECT * FROM account WHERE database_uid = ?" ,(row["database_uid"],)).fetchone()
  if account is None:
    storage_db.close()
    raise RecordError(f"the storage database has no account of database uid {row['database_uid']}")
  return storage_db ,account

def count_of__below(storage_db ,database_uid):
  "how many accounts are below the account database_uid in storage_db, those deallocated left out"
  return storage_db.execute(
    "WITH RECURSIVE below(database_uid) AS ("
    " SELECT database_uid FROM account WHERE parent__database_uid = ?"
    " UNION SELECT a.database_uid FROM account a JOIN below b ON a.parent__database_uid = b.database_uid)"
    " SELECT COUNT(*) AS n FROM account WHERE database_uid IN below AND state != 'deallocated'" ,(database_uid,)).fetchone()["n"]

def below__not_in(system_db ,system_account__name ,list__state):
  "the names of the accounts directly below a system account in use, in its storage database, whose state is not in list__state"
  storage_db ,account = row__storage_account(system_db ,system_account__name)
  try:
    return [a["name"] for a in storage_db.execute("SELECT name ,state FROM account WHERE parent__database_uid = ? ORDER BY name"
                                                 ,(account["database_uid"],)) if a["state"] not in list__state]
  finally:
    storage_db.close()

def child_account__make__problem(system_db ,account__asking ,name):
  """
  The problems with a request by account__asking to make the account name,
  whose parent is the name before its last separator. The parent is the
  asking account or an account below it, in use and active; name is free
  here and in the parent's storage database; and there is room under the
  limit of the parent and of each account above it.
  """
  parent = name.rsplit(SEPARATOR ,1)[0]
  if sa.system_account(name) is not None or (DIRPA__HOME / name).exists():
    return [f"{name} exists already on this system"]
  if parent != account__asking:
    found = account__below(system_db ,account__asking ,parent ,("active",) ,is__mounted=False)
    if found:
      return [f"its parent: {p}" for p in found]
  try:
    storage_db ,account = row__storage_account(system_db ,parent)
  except RecordError as error:
    return [str(error)]
  try:
    list__problem = []
    if account["state"] != "active":
      list__problem.append(f"its parent {parent} is {account['state']}")
    if account["name"] != parent:
      list__problem.append(f"the storage account of {parent} is named {account['name']}, a branch;"
                           " a child account is made only for an account whose two names are the same")
    if storage_db.execute("SELECT 1 FROM account WHERE name = ?" ,(name,)).fetchone():
      list__problem.append(f"{name} is in the storage database already")
    # room under the limit of the parent and of each account above it
    each = account
    for _ in range(DEPTH_MAX):
      maximum = limit__of(system_db ,each["name"])
      count = count_of__below(storage_db ,each["database_uid"])
      if count + 1 > maximum:
        list__problem.append(f"{each['name']} has {count} accounts below it, and its limit is {maximum};"
                             " the administrator sets another with limit set")
      if each["parent__database_uid"] is None: break
      each = storage_db.execute("SELECT * FROM account WHERE database_uid = ?" ,(each["parent__database_uid"],)).fetchone()
      if each is None: break
    return list__problem
  finally:
    storage_db.close()
