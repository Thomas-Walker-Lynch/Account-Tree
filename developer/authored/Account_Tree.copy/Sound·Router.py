# -*- mode: python; coding: utf-8; python-indent-offset: 2; indent-tabs-mode: nil -*-
"""
Sound·Router - the router: what carries out an account's sound in its own
PipeWire, under the account. See developer/design_audio.html.

The router asks the request gate, with sound_route_show, what it is to do,
at start and each time it is told to reload (SIGHUP), and builds a plan from
the answer:

  in the hub, the login account's PipeWire
    a node for each bus, a null sink of media class Audio/Bus, which the
    sound settings do not list and WirePlumber does not link
    for each FIFO of the tree, a pipe-tunnel: on a gather end, a playback
    stream that reads the FIFO and that the router links into the bus; on a
    broadcast end, a capture stream that the router links from the bus's
    monitor and that writes the FIFO
    for each device connection, a loopback: @output on a broadcast end,
    from the bus's monitor to the hub's chosen output; @input on a gather
    end, from the hub's chosen input into the bus. The device side of each
    loopback is left to WirePlumber, so it follows the person's choice
    the bit bucket, a null sink and a null source

  in another account's PipeWire
    for each FIFO, a pipe-tunnel: a sink named for the bus on a gather end,
    a source named for it on a broadcast end
    the bit bucket, as the account's default output and input
    its program lines, which the router matches each new stream against

Each tunnel and loopback runs as a process of its own, pipewire -c <conf>,
so one is started or stopped without restarting the account's PipeWire. The
nodes are made by one pw-cli the router keeps running, so they go when the
router does. The router watches the account's PipeWire with pw-dump --monitor:
it makes the links the plan holds in the hub with pw-link, and removes a
link between nodes the plan links that it does not hold, and gives each new stream of a program a target with pw-metadata,
the bus end its first matching line names, or the bit bucket. Streams
Account-Tree makes carry the property account_tree.stream, and are left
alone.

  plan__of(route ,name)   the plan for a route, as sound_route_show answers
  Router                  carries out plans, from run() until stopped
"""

import json ,os ,re ,signal ,subprocess ,sys ,threading ,time
import queue as queue_
from pathlib import Path

PROP__MARK = "account_tree.stream"
LIST__CHANNEL = ("FL" ,"FR")
NODE__BIT_BUCKET_SINK = "Account-Tree.bit_bucket.sink"
NODE__BIT_BUCKET_SOURCE = "Account-Tree.bit_bucket.source"
PREFIX__NODE = "Account-Tree."
CLASS__PLAYING = "Stream/Output/Audio"
CLASS__CAPTURING = "Stream/Input/Audio"
SECOND__RETRY = 2.0
SECOND__POLL = 5.0
UNLINK__MAX = 3


# --------------------------------------------------------------------------------
# names

def node__bus(number):
  "in the hub, the node of bus number"
  return f"Account-Tree.bus.{number}"

def node__end(number ,end):
  "in another account, the sink or source of one end of bus number"
  return f"Account-Tree.bus.{number}.{end}"

def node__tunnel(account ,number ,end):
  "in the hub, the stream of one account's FIFO for one end of bus number"
  return f"Account-Tree.{end}.{account}.{number}"

def node__device(device ,number):
  "in the hub, the loopback side the router links, for a device on bus number"
  return f"Account-Tree.{device.lstrip('@')}.{number}"

def quote(text):
  "a string in PipeWire's configuration syntax"
  return '"' + str(text).replace("\\" ,"\\\\").replace('"' ,'\\"') + '"'


# --------------------------------------------------------------------------------
# the plan

class Plan:
  """
  What the router is to run: tunnel, configuration text by key, one process
  each; node, the properties of each node pw-cli makes; link, the pairs of
  ports to link, output then input, each written node.name:port.name; and
  rule, the program lines in order, as (end ,node to target ,pattern).
  """
  def __init__(self):
    self.is__hub = False
    self.tunnel = {}
    self.node = []
    self.link = set()
    self.rule = []

  def text(self):
    "the plan, to read"
    line = [f"hub: {'yes' if self.is__hub else 'no'}" ,"node"]
    line += [f"  {n}" for n in self.node] or ["  -"]
    line += ["process"]
    line += [f"  {key}" for key in sorted(self.tunnel)] or ["  -"]
    line += ["link"]
    line += [f"  {o} -> {i}" for o ,i in sorted(self.link)] or ["  -"]
    line += ["rule"]
    line += [f"  {end:<10} {pattern.pattern:<30} -> {target}" for end ,target ,pattern in self.rule] or ["  -"]
    return "\n".join(line)

def conf__module(name ,args):
  "the configuration of a pipewire -c process that loads one module, with args in PipeWire's syntax"
  return ("context.properties = { log.level = 2 }\n"
          "context.modules = [\n"
          "  { name = libpipewire-module-protocol-native }\n"
          "  { name = libpipewire-module-client-node }\n"
          "  { name = libpipewire-module-adapter }\n"
          f"  {{ name = {name}\n"
          f"    args = {args} }}\n"
          "]\n")

def node__null(name ,description ,media_class ,priority):
  "the properties pw-cli is given to make a null node"
  return ("{ factory.name = support.null-audio-sink"
          f" node.name = {quote(name)} node.description = {quote(description)}"
          f" media.class = {quote(media_class)} audio.position = [ FL FR ]"
          f" priority.session = {priority} {PROP__MARK} = true object.linger = false }}")

def plan__of(route ,name):
  """
  The plan for the system account name, from route, the value
  sound_route_show answers; an empty plan for None.
  """
  plan = Plan()
  if route is None:
    return plan
  plan.is__hub = route["is__hub"]
  map__bus = {bus["number"]: bus["name"] for bus in route["list__bus"]}
  # the bit bucket: the default output and input of an account other than
  # the login account, whose defaults are the person's chosen devices
  priority = 1 if plan.is__hub else 2000
  plan.node.append(node__null(NODE__BIT_BUCKET_SINK ,"bit bucket" ,"Audio/Sink" ,priority))
  plan.node.append(node__null(NODE__BIT_BUCKET_SOURCE ,"bit bucket" ,"Audio/Source/Virtual" ,priority))
  if plan.is__hub:
    for number ,bus_name in sorted(map__bus.items()):
      plan.node.append(node__null(node__bus(number) ,bus_name ,"Audio/Bus" ,0))
    for fifo in route["list__fifo"]:
      number ,end = fifo["bus__number"] ,fifo["end"]
      stream = node__tunnel(fifo["account"] ,number ,end)
      mode = "playback" if end == "gather" else "capture"
      plan.tunnel[f"{end}.{fifo['account']}.{number}"] = conf__module("libpipewire-module-pipe-tunnel"
        ,f"{{ tunnel.mode = {mode} pipe.filename = {quote(fifo['path'])}"
         f" stream.props = {{ node.name = {quote(stream)} node.description = {quote(fifo['account'] + ' on ' + map__bus.get(number ,str(number)))}"
         f" node.autoconnect = false node.dont-reconnect = true {PROP__MARK} = true }} }}")
      for c in LIST__CHANNEL:
        if end == "gather":
          plan.link.add((f"{stream}:output_{c}" ,f"{node__bus(number)}:input_{c}"))
        else:
          plan.link.add((f"{node__bus(number)}:monitor_{c}" ,f"{stream}:input_{c}"))
    for device in route["list__device"]:
      number ,end = device["bus__number"] ,device["end"]
      if number not in map__bus: continue
      near = node__device(device["device"] ,number)
      if device["device"] == "@output" and end == "broadcast":
        args = (f"{{ node.description = {quote(map__bus[number] + ' to the chosen output')} audio.position = [ FL FR ]"
                f" capture.props = {{ node.name = {quote(near)} media.class = Stream/Input/Audio node.autoconnect = false {PROP__MARK} = true }}"
                f" playback.props = {{ node.name = {quote(near + '.playback')} media.class = Stream/Output/Audio {PROP__MARK} = true }} }}")
        for c in LIST__CHANNEL:
          plan.link.add((f"{node__bus(number)}:monitor_{c}" ,f"{near}:input_{c}"))
      elif device["device"] == "@input" and end == "gather":
        args = (f"{{ node.description = {quote('the chosen input to ' + map__bus[number])} audio.position = [ FL FR ]"
                f" capture.props = {{ node.name = {quote(near + '.capture')} media.class = Stream/Input/Audio {PROP__MARK} = true }}"
                f" playback.props = {{ node.name = {quote(near)} media.class = Stream/Output/Audio node.autoconnect = false {PROP__MARK} = true }} }}")
        for c in LIST__CHANNEL:
          plan.link.add((f"{near}:output_{c}" ,f"{node__bus(number)}:input_{c}"))
      else:
        # @output gathered or @input broadcast: no direction of sound fits
        continue
      plan.tunnel[f"{device['device'].lstrip('@')}.{number}"] = conf__module("libpipewire-module-loopback" ,args)
    return plan
  for fifo in route["list__fifo"]:
    number ,end = fifo["bus__number"] ,fifo["end"]
    mode = "sink" if end == "gather" else "source"
    plan.tunnel[f"{end}.{number}"] = conf__module("libpipewire-module-pipe-tunnel"
      ,f"{{ tunnel.mode = {mode} pipe.filename = {quote(fifo['path'])}"
       f" stream.props = {{ node.name = {quote(node__end(number ,end))} node.description = {quote(map__bus.get(number ,str(number)))}"
       f" priority.session = 1000 {PROP__MARK} = true }} }}")
  set__reached = {(f["bus__number"] ,f["end"]) for f in route["list__fifo"]}
  for line in route["list__line"]:
    if (line["bus__number"] ,line["end"]) not in set__reached: continue
    try:
      pattern = re.compile(line["pattern"])
    except re.error:
      continue
    plan.rule.append((line["end"] ,node__end(line["bus__number"] ,line["end"]) ,pattern))
  return plan


# --------------------------------------------------------------------------------
# what the account's PipeWire holds, from pw-dump --monitor

class Graph:
  "the objects of the account's PipeWire, by id, kept up to date from pw-dump's updates"
  def __init__(self):
    self.object = {}

  def update(self ,list__object):
    for o in list__object:
      if o.get("info") is None:
        self.object.pop(o["id"] ,None); continue
      known = self.object.setdefault(o["id"] ,{"type": o.get("type") ,"info": {} ,"props": {}})
      if o.get("type"): known["type"] = o["type"]
      info = o["info"]
      known["info"].update({k: v for k ,v in info.items() if k != "props"})
      if info.get("props"):
        known["props"] = info["props"]

  def of_type(self ,suffix):
    return [(i ,o) for i ,o in self.object.items() if (o["type"] or "").endswith(suffix)]

  def port__name(self):
    "port id -> node.name:port.name, for every port whose node is known"
    node = {i: o["props"].get("node.name") for i ,o in self.of_type(":Node")}
    result = {}
    for i ,o in self.of_type(":Port"):
      n = node.get(o["props"].get("node.id") ,None)
      if n is None:
        n = node.get(o["info"].get("node-id"))
      if n is not None and o["props"].get("port.name"):
        result[i] = f"{n}:{o['props']['port.name']}"
    return result

  def link(self):
    "the links, as (output port name ,input port name)"
    name = self.port__name()
    result = set()
    for _ ,o in self.of_type(":Link"):
      out ,in_ = name.get(o["info"].get("output-port-id")) ,name.get(o["info"].get("input-port-id"))
      if out and in_:
        result.add((out ,in_))
    return result

  def binary__of(self ,props):
    "the program a node's stream is of: its application.process.binary, or its client's"
    binary = props.get("application.process.binary")
    if binary: return binary
    client = self.object.get(props.get("client.id"))
    return (client or {}).get("props" ,{}).get("application.process.binary")


def is__marked(props):
  return str(props.get(PROP__MARK ,"")).lower() in ("true" ,"1")


# --------------------------------------------------------------------------------
# the router

class Router:
  """
  Carries out the plans for the account it runs under. log(text) reports;
  fetch() is to return the route, or None, sound_route_show's answer.
  """
  def __init__(self ,name ,fetch ,log):
    self.name ,self.fetch ,self.log = name ,fetch ,log
    self.plan = Plan()
    self.graph = Graph()
    self.event = queue_.Queue()
    self.process = {}        # key -> (Popen ,conf text)
    self.node_holder = None  # (Popen ,list of node properties)
    self.set__routed = set()
    self.count__unlink = {}
    self.monitor = None
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    self.dirpa__conf = Path(runtime) / "Account-Tree-router"

  # ---- processes

  def tunnel__apply(self):
    self.dirpa__conf.mkdir(mode=0o700 ,exist_ok=True)
    for key in [k for k in self.process if k not in self.plan.tunnel]:
      self.process__stop(key)
    for key ,text in self.plan.tunnel.items():
      running = self.process.get(key)
      if running and running[1] == text and running[0].poll() is None: continue
      if running: self.process__stop(key)
      fpa = self.dirpa__conf / f"{key}.conf"
      fpa.write_text(text ,encoding="utf-8")
      self.process[key] = (subprocess.Popen(["pipewire" ,"-c" ,str(fpa)] ,stdin=subprocess.DEVNULL
                                            ,stdout=subprocess.DEVNULL ,stderr=subprocess.DEVNULL) ,text)
      self.log(f"started {key}")

  def process__stop(self ,key):
    p ,_ = self.process.pop(key)
    if p.poll() is None:
      p.terminate()
      try: p.wait(timeout=5)
      except subprocess.TimeoutExpired: p.kill()
    try: (self.dirpa__conf / f"{key}.conf").unlink()
    except OSError: pass
    self.log(f"stopped {key}")

  def node__apply(self):
    if self.node_holder and self.node_holder[1] == self.plan.node and self.node_holder[0].poll() is None:
      return
    self.node__stop()
    if not self.plan.node: return
    p = subprocess.Popen(["pw-cli"] ,stdin=subprocess.PIPE ,stdout=subprocess.DEVNULL ,stderr=subprocess.DEVNULL ,text=True)
    for props in self.plan.node:
      p.stdin.write(f"create-node adapter {props}\n")
    p.stdin.flush()
    self.node_holder = (p ,list(self.plan.node))
    self.log(f"made {len(self.plan.node)} nodes")

  def node__stop(self):
    if self.node_holder:
      p ,_ = self.node_holder
      self.node_holder = None
      try: p.stdin.close()
      except OSError: pass
      if p.poll() is None:
        p.terminate()
        try: p.wait(timeout=5)
        except subprocess.TimeoutExpired: p.kill()

  def stop(self):
    for key in list(self.process): self.process__stop(key)
    self.node__stop()
    if self.monitor and self.monitor.poll() is None:
      self.monitor.terminate()

  # ---- watching

  def monitor__start(self):
    self.graph = Graph()
    self.set__routed = set()
    try:
      self.monitor = subprocess.Popen(["pw-dump" ,"--monitor" ,"--no-colors"] ,stdin=subprocess.DEVNULL
                                      ,stdout=subprocess.PIPE ,stderr=subprocess.DEVNULL ,text=True)
    except OSError as error:
      self.log(f"pw-dump: {error}"); self.monitor = None; return
    threading.Thread(target=self.monitor__read ,args=(self.monitor,) ,daemon=True).start()

  def monitor__read(self ,p):
    decoder = json.JSONDecoder()
    buffer = ""
    for chunk in iter(lambda: p.stdout.read(4096) ,""):
      buffer += chunk
      while True:
        stripped = buffer.lstrip()
        if not stripped: buffer = ""; break
        try:
          value ,end = decoder.raw_decode(stripped)
        except ValueError:
          break
        buffer = stripped[end:]
        if isinstance(value ,list):
          self.event.put(("graph" ,value))
    self.event.put(("monitor ended" ,p))

  # ---- acting on the graph

  def reconcile(self):
    if self.plan.is__hub:
      self.link__reconcile()
    self.stream__route()

  def link__reconcile(self):
    """
    Make the planned links that are missing, and remove a link between two of
    the nodes the plan links, the buses and the sides of the tunnels and
    loopbacks it joins to them, that the plan does not hold. A link to any
    other node is left alone: the device side of a loopback, and the bit
    bucket, are WirePlumber's to link, and the hub's chosen output can be
    the bit bucket. Should something keep making a link the router removes,
    the router stops removing it after a few times, and says so, rather than
    the two working against each other without end.
    """
    name = set(self.graph.port__name().values())
    now = self.graph.link()
    for out ,in_ in sorted(self.plan.link - now):
      if out in name and in_ in name:
        if subprocess.run(["pw-link" ,out ,in_] ,stdin=subprocess.DEVNULL ,capture_output=True).returncode == 0:
          self.log(f"linked {out} -> {in_}")
    set__managed = {port.rpartition(":")[0] for pair in self.plan.link for port in pair}
    for out ,in_ in sorted(now - self.plan.link):
      if out.rpartition(":")[0] not in set__managed or in_.rpartition(":")[0] not in set__managed: continue
      count = self.count__unlink.get((out ,in_) ,0)
      if count >= UNLINK__MAX:
        if count == UNLINK__MAX:
          self.log(f"left {out} -> {in_}: something links it again each time it is removed")
          self.count__unlink[(out ,in_)] = count + 1
        continue
      if subprocess.run(["pw-link" ,"-d" ,out ,in_] ,stdin=subprocess.DEVNULL ,capture_output=True).returncode == 0:
        self.count__unlink[(out ,in_)] = count + 1
        self.log(f"unlinked {out} -> {in_}")

  def target__of(self ,media_class ,binary):
    "the node a new stream is to be given as its target"
    end = "gather" if media_class == CLASS__PLAYING else "broadcast"
    if binary:
      for rule_end ,target ,pattern in self.plan.rule:
        if rule_end == end and pattern.fullmatch(binary):
          return target
    return NODE__BIT_BUCKET_SINK if end == "gather" else NODE__BIT_BUCKET_SOURCE

  def stream__route(self):
    if not self.plan.node: return
    present = set()
    for i ,o in self.graph.of_type(":Node"):
      props = o["props"]
      media_class = props.get("media.class")
      if media_class not in (CLASS__PLAYING ,CLASS__CAPTURING) or is__marked(props): continue
      present.add(i)
      if i in self.set__routed: continue
      binary = self.graph.binary__of(props)
      target = self.target__of(media_class ,binary)
      done = subprocess.run(["pw-metadata" ,str(i) ,"target.object" ,target] ,stdin=subprocess.DEVNULL ,capture_output=True)
      if done.returncode == 0:
        self.set__routed.add(i)
        self.log(f"routed {binary or props.get('application.name') or i} to {target}")
    self.set__routed &= present

  # ---- running

  def reload(self):
    route = self.fetch()
    self.plan = plan__of(route ,self.name)
    self.count__unlink = {}
    self.node__apply()
    self.tunnel__apply()
    self.set__routed = set()
    self.reconcile()
    self.log(f"reloaded: {len(self.plan.tunnel)} processes, {len(self.plan.link)} links, {len(self.plan.rule)} rules")

  def run(self):
    signal.signal(signal.SIGHUP ,lambda *_: self.event.put(("reload" ,None)))
    signal.signal(signal.SIGTERM ,lambda *_: self.event.put(("stop" ,None)))
    signal.signal(signal.SIGINT ,lambda *_: self.event.put(("stop" ,None)))
    self.monitor__start()
    self.reload()
    try:
      while True:
        try:
          kind ,value = self.event.get(timeout=SECOND__POLL)
        except queue_.Empty:
          kind ,value = "poll" ,None
        if kind == "stop":
          break
        if kind == "reload":
          self.reload(); continue
        if kind == "graph":
          self.graph.update(value)
        elif kind == "monitor ended":
          if value is self.monitor:
            time.sleep(SECOND__RETRY)
            self.monitor__start()
          continue
        elif kind == "poll":
          dead = [k for k ,(p ,_) in self.process.items() if p.poll() is not None]
          if dead or (self.node_holder and self.node_holder[0].poll() is not None):
            for k in dead: self.log(f"{k} ended; starting it again")
            self.node__apply(); self.tunnel__apply()
        self.reconcile()
    finally:
      self.stop()
