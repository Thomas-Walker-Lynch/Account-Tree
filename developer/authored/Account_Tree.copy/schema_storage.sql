-- schema_storage.sql
--
-- The storage database, standard 5.0, at
-- <storage root>/home/Account-Tree/database.sqlite3. It records the storage accounts
-- kept on the storage. It confers nothing on any system: which storage accounts
-- are the same accounts as system accounts on a system is recorded by that
-- system, in its system database.
--
--   database uuid   names this database; a copy of the database carries it too
--   database uid    a storage account's uid in this database's own numbering,
--                   which counts down from 1999999999; the account's files on the
--                   storage carry it
--
-- A database has no name for people: a name would travel with every copy of
-- the database and come to mislead. It is shown by its database uuid, series
-- number, head hash and the time of its last change.
-- Times are for people to read; the series number in identity is authoritative.

-- This database: its database uuid and the head of its hash chain. One row.
-- genesis_uuid is the database uuid it was made with, from which its chain
-- begins. A database made by branching from another gets a new database uuid,
-- and records the database it branched from and the head they parted after.
CREATE TABLE identity (
  database_uuid        TEXT NOT NULL,
  genesis_uuid         TEXT NOT NULL,
  branch_of            TEXT,              -- database uuid this one branched from
  branch__after_series  INTEGER,
  branch__after_head    TEXT,
  series               INTEGER NOT NULL,  -- series number of the last transaction
  head_hash            TEXT NOT NULL,     -- hash of the last transaction
  created              TEXT NOT NULL
);

-- The Account-Tree standards this database follows.
CREATE TABLE standard (
  version  TEXT PRIMARY KEY
);

-- The storage accounts this database carries. A storage account's parent is
-- named by its name, and by its database uid when the parent is carried here.
CREATE TABLE account (
  database_uid         INTEGER PRIMARY KEY,
  name                 TEXT NOT NULL UNIQUE,
  parent__database_uid  INTEGER,              -- NULL when the parent is not carried here
  parent_name          TEXT,                 -- NULL for an account whose parent is root
  state                TEXT NOT NULL CHECK (state IN ('active' ,'deprecated' ,'deallocated')),
  created              TEXT NOT NULL,
  changed              TEXT NOT NULL
);

-- Every database uid this database has given out. None is given out twice.
CREATE TABLE database_uid (
  database_uid  INTEGER PRIMARY KEY,
  state         TEXT NOT NULL CHECK (state IN ('in use' ,'retired'))
);

-- The systems that have seen this database: those on which a storage account
-- of it has been made the same account as a system account, with when that
-- was first, and when the database was last attached or detached there. For
-- the owner of the storage, and for storage delete, which will not leave a
-- system mapping a database that no longer exists. Never authority: each
-- system's own system database is the record of which accounts are the same.
CREATE TABLE system_seen (
  system_uuid  TEXT PRIMARY KEY,
  first        TEXT NOT NULL,
  last         TEXT NOT NULL
);

-- Other databases this one knows, and their storage accounts that are the
-- same accounts as storage accounts here. Not used in 5.0.
CREATE TABLE acquaintance_database (
  database_uuid  TEXT PRIMARY KEY,
  introduced     TEXT NOT NULL
);

CREATE TABLE same_account__database (
  other_database__uuid  TEXT NOT NULL,
  other_database__uid   INTEGER NOT NULL,
  database_uid         INTEGER NOT NULL,
  PRIMARY KEY (other_database__uuid ,other_database__uid),
  UNIQUE (other_database__uuid ,database_uid)
);

-- Tables added after storage databases were first made; opening a database
-- that lacks one makes it (see Database.schema_added__text).

-- Each share: the member account is in the own group of the sharing account,
-- so it reaches what the sharing account gives its group. Both accounts are
-- this storage database's, by database uid. Attach makes each share on the
-- system the storage is attached to; this table, not a system's saved
-- groups, is the authority for shares among the storage's accounts, so a
-- share made or removed on one system holds on every other.
CREATE TABLE IF NOT EXISTS account_share (
  share__database_uid   INTEGER NOT NULL,
  member__database_uid  INTEGER NOT NULL,
  made                  TEXT NOT NULL,
  PRIMARY KEY (share__database_uid ,member__database_uid)
);

-- What a storage account's system account has that its home does not carry:
-- its password, as /etc/shadow holds the hash, its password aging, comment
-- and shell. Written at each unplug, from the system unplugged from, while the
-- storage can still be read, and given to the system account made again at
-- the next plug, on whichever system: a person's password is the same on every
-- system the storage is plugged into. A field empty in /etc/shadow is NULL.
CREATE TABLE IF NOT EXISTS account_setting (
  database_uid            INTEGER PRIMARY KEY,
  comment                 TEXT NOT NULL,
  shell                   TEXT NOT NULL,
  password                TEXT NOT NULL,   -- the hash, as /etc/shadow holds it
  password__last_change   INTEGER,         -- days since 1970-01-01
  password__minimum_day   INTEGER,
  password__maximum_day   INTEGER,
  password__warning_day   INTEGER,
  password__inactive_day  INTEGER,
  account__expire         INTEGER,         -- days since 1970-01-01
  saved                   TEXT NOT NULL
);

-- Sound; see design_audio.html. The buses of each tree, made only from its
-- login account, and numbered within the tree.
CREATE TABLE IF NOT EXISTS sound_bus (
  login__database_uid  INTEGER NOT NULL,
  bus__number          INTEGER NOT NULL,
  name                 TEXT NOT NULL,
  made                 TEXT NOT NULL,
  PRIMARY KEY (login__database_uid ,bus__number),
  UNIQUE (login__database_uid ,name)
);

-- A row for each permit an account holds for one end of one bus of its
-- tree; made is when it was issued. Whether it is in force is worked out:
-- held, and the parent's in force, or, for the login account, its grant of
-- sound held.
CREATE TABLE IF NOT EXISTS sound_permit_bus_end (
  database_uid  INTEGER NOT NULL,
  bus__number   INTEGER NOT NULL,
  bus_end       TEXT NOT NULL CHECK (bus_end IN ('gather' ,'broadcast')),
  made          TEXT NOT NULL,
  PRIMARY KEY (database_uid ,bus__number ,bus_end)
);

-- A row for each permit an account holds for a device of the hub; made is
-- when it was issued.
CREATE TABLE IF NOT EXISTS sound_permit_device (
  database_uid  INTEGER NOT NULL,
  device        TEXT NOT NULL CHECK (device IN ('@output' ,'@input')),
  made          TEXT NOT NULL,
  PRIMARY KEY (database_uid ,device)
);

-- A row for each account that has a connection table, made when its first
-- permit is issued and kept from then on, its lines or none.
CREATE TABLE IF NOT EXISTS sound_connection_table (
  database_uid  INTEGER PRIMARY KEY,
  made          TEXT NOT NULL
);

-- The lines of each connection table, in order. A comment line, or a blank
-- one, has no end and no bus, and its text as its endpoint.
CREATE TABLE IF NOT EXISTS sound_connection (
  database_uid    INTEGER NOT NULL,
  line__number    INTEGER NOT NULL,
  bus_end         TEXT CHECK (bus_end IN ('gather' ,'broadcast')),
  bus__number     INTEGER,
  endpoint__kind  TEXT NOT NULL CHECK (endpoint__kind IN ('program' ,'device' ,'comment')),
  endpoint        TEXT NOT NULL,
  PRIMARY KEY (database_uid ,line__number)
);

-- Every change. hash covers previous_hash, series, description, change and nonce.
CREATE TABLE transaction_log (
  series         INTEGER PRIMARY KEY,
  previous_hash  TEXT NOT NULL,
  nonce          TEXT NOT NULL,
  description    TEXT NOT NULL,
  change         TEXT NOT NULL,     -- JSON list of [statement ,parameters]
  hash           TEXT NOT NULL,
  time           TEXT NOT NULL
);
