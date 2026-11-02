"""
Scarcity Sim — Week 1 (no LLM yet)

Layer 1  World:  plain deterministic code. Food is scarce and regrows slowly.
Layer 2  Agents: stats (state) + values (personality) + memory (starts blank).
                 Decisions use utility scoring. Every spot marked `LLM HOOK`
                 is where a language model plugs in later.
Output:  events.json — the raw history a "chronicler" will later turn into story.

Run:  python sim.py
"""
import json
import random
from dataclasses import dataclass, field

SEED = 7
TICKS = 150
random.seed(SEED)


# ───────────────────────── MEMORY ─────────────────────────
@dataclass
class Memory:
    tick: int
    text: str
    importance: float      # 0..1  how much this matters
    valence: float         # -1..1 bad ↔ good
    about: list            # names of agents involved
    kind: str = "observation"   # or "reflection"


class MemoryStream:
    """Starts empty. Grows every time the agent sees or does something."""

    def __init__(self):
        self.items: list[Memory] = []

    def add(self, m: Memory):
        self.items.append(m)

    def retrieve(self, now, about=None, k=5, decay=0.97):
        """Score = recency + importance + relevance (Generative Agents formula).
        Relevance is a name match for now; swap in embedding similarity later."""
        def score(m):
            recency = decay ** (now - m.tick)
            relevance = 1.0 if (about and about in m.about) else 0.0
            return recency + m.importance + relevance
        return sorted(self.items, key=score, reverse=True)[:k]


# ───────────────────────── AGENT ─────────────────────────
class Agent:
    def __init__(self, name, values):
        self.name = name
        # STATE — what the agent has 
        self.health = 100.0
        self.money = 10.0
        self.food = 3
        self.affinity: dict[str, float] = {}   # pairwise, -1..1
        # PERSONALITY — what the agent cares about (sums to 1)
        self.values = values
        # MEMORY — starts blank
        self.memory = MemoryStream()
        self.alive = True

    @property
    def social(self):
        """Derived stat: sum of positive relationships."""
        return sum(max(0.0, a) for a in self.affinity.values())

    def remember(self, tick, text, importance, valence, about=(), kind="observation"):
        self.memory.add(Memory(tick, text, importance, valence, list(about), kind))

    def opinion_of(self, other, now):
        """Affinity, bent by what memory surfaces about them.  LLM HOOK"""
        recalled = [m for m in self.memory.retrieve(now, about=other.name, k=4)
                    if other.name in m.about]
        mem_bias = sum(m.valence * m.importance for m in recalled) / 4
        return self.affinity.get(other.name, 0.0) + mem_bias

    def nudge(self, other, delta):
        a = self.affinity.get(other.name, 0.0) + delta
        self.affinity[other.name] = max(-1.0, min(1.0, a))

    # needs: rise as stats fall (non-linear → desperation)
    def food_need(self):
        return {0: 1.0, 1: 0.6, 2: 0.3}.get(self.food, 0.1) * (1.5 - self.health / 200)

    def money_need(self):
        return 1 / (1 + self.money / 8)

    def social_need(self):
        return 1 / (1 + self.social)


# ───────────────────────── WORLD ─────────────────────────
class World:
    def __init__(self, agents, food_cap=50, regen=5):
        self.agents = agents
        self.food_cap, self.food_pool, self.regen = food_cap, food_cap, regen
        self.tick = 0
        self.log = []

    def living(self):
        return [a for a in self.agents if a.alive]

    def price(self):
        """Scarcity sets the price."""
        return round(2 + 10 * (1 - self.food_pool / self.food_cap), 1)

    def emit(self, kind, actor, target=None, detail=""):
        self.log.append({"tick": self.tick, "event": kind, "actor": actor.name,
                         "target": target.name if target else None, "detail": detail})

    def witnesses(self, *exclude):
        others = [a for a in self.living() if a not in exclude]
        return random.sample(others, k=min(2, len(others)))

    # ───── actions ─────
    def forage(self, a):
        chance = self.food_pool / self.food_cap
        got = sum(1 for _ in range(2) if random.random() < chance and self.food_pool > 0)
        self.food_pool -= got
        a.food += got
        a.remember(self.tick, f"I foraged {got} food", 0.1, 0.2 if got else -0.2)
        self.emit("forage", a, detail=f"got {got}")

    def work(self, a):
        a.money += 4
        self.emit("work", a)

    def buy(self, a):
        p = self.price()
        a.money -= p
        a.food += 1
        self.food_pool -= 1
        self.emit("buy", a, detail=f"price {p}")

    def share(self, a, t):
        a.food -= 1
        t.food += 1
        a.nudge(t, 0.2); t.nudge(a, 0.35)
        a.remember(self.tick, f"I gave food to {t.name}", 0.4, 0.5, [t.name])
        t.remember(self.tick, f"{a.name} gave me food when I needed it", 0.7, 0.9, [a.name])
        self.emit("share", a, t)

    def steal(self, a, t):
        if random.random() < 0.6:
            t.food -= 1
            a.food += 1
            t.nudge(a, -0.6)
            a.remember(self.tick, f"I stole from {t.name}", 0.5, -0.1, [t.name])
            t.remember(self.tick, f"{a.name} stole my food", 0.9, -1.0, [a.name])
            for w in self.witnesses(a, t):
                w.nudge(a, -0.2)
                w.remember(self.tick, f"I saw {a.name} rob {t.name}", 0.6, -0.6, [a.name, t.name])
            self.emit("steal", a, t, "success")
        else:
            t.nudge(a, -0.4)
            t.remember(self.tick, f"{a.name} tried to rob me", 0.8, -0.8, [a.name])
            self.emit("steal", a, t, "caught")

    def talk(self, a, t):
        a.nudge(t, 0.1); t.nudge(a, 0.1)
        a.remember(self.tick, f"Talked with {t.name}", 0.2, 0.3, [t.name])
        t.remember(self.tick, f"Talked with {a.name}", 0.2, 0.3, [a.name])
        self.emit("talk", a, t)

    # ───── decision: utility AI ─────  (LLM HOOK: replace with a model choosing from top-3)
    def decide(self, a):
        v, now = a.values, self.tick
        others = [o for o in self.living() if o is not a]
        opts = []

        opts.append((v["health"] * a.food_need() * 2 * self.food_pool / self.food_cap,
                     lambda: self.forage(a)))
        opts.append((v["money"] * a.money_need(), lambda: self.work(a)))
        if a.money >= self.price():
            opts.append((v["health"] * a.food_need() * 1.5
                         - v["money"] * a.money_need() * self.price() / 10,
                         lambda: self.buy(a)))

        for t in others:
            op = a.opinion_of(t, now)
            if a.food >= 3:
                opts.append((v["social"] * a.social_need() * 0.8 + 0.4 * op
                             + 0.3 * t.food_need() * max(0, op),
                             lambda t=t: self.share(a, t)))
            if t.food >= 1:
                desperation = a.food_need() * (1 - a.health / 100) * 3
                opts.append((v["health"] * desperation - v["social"] * 0.4 - 0.6 * op,
                             lambda t=t: self.steal(a, t)))
            opts.append((v["social"] * a.social_need() * 0.5 + 0.2 * op,
                         lambda t=t: self.talk(a, t)))

        noisy = [(u + random.gauss(0, 0.05), act) for u, act in opts]
        max(noisy, key=lambda x: x[0])[1]()

    # ───── reflection ─────  (LLM HOOK: model writes the belief in its own words)
    def reflect(self, a):
        for o in self.agents:
            if o is a:
                continue
            mems = [m for m in a.memory.items if o.name in m.about and m.kind == "observation"]
            if len(mems) < 2:
                continue
            total = sum(m.valence * m.importance for m in mems)
            if total < -1.0:
                a.remember(self.tick, f"{o.name} cannot be trusted", 0.9, -0.9, [o.name], "reflection")
                self.emit("reflect", a, o, "distrust")
            elif total > 1.0:
                a.remember(self.tick, f"{o.name} is a true friend", 0.9, 0.9, [o.name], "reflection")
                self.emit("reflect", a, o, "bond")

    # ───── one tick of time ─────
    def step(self):
        self.tick += 1
        order = self.living()
        random.shuffle(order)
        for a in order:
            if a.alive:
                self.decide(a)
        for a in self.living():               # upkeep: eat or starve
            if a.food > 0:
                a.food -= 1
                a.health = min(100, a.health + 4)
            else:
                a.health -= 12
            if a.health <= 0:
                a.alive = False
                self.emit("death", a, detail="starved")
                for o in self.living():
                    feel = o.affinity.get(a.name, 0)
                    o.remember(self.tick, f"{a.name} starved to death", 0.5 + abs(feel) / 2,
                               -0.5 if feel >= 0 else 0.2, [a.name])
        if self.tick % 25 == 0:
            for a in self.living():
                self.reflect(a)
        self.food_pool = min(self.food_cap, self.food_pool + self.regen)


# ───────────────────────── RUN ─────────────────────────
def random_values():
    w = [random.random() for _ in range(3)]
    s = sum(w)
    return {"health": w[0] / s, "money": w[1] / s, "social": w[2] / s}


if __name__ == "__main__":
    names = ["Arin", "Bex", "Cato", "Dara", "Elio", "Fen", "Gida", "Hux"]
    agents = [Agent(n, random_values()) for n in names]
    world = World(agents)

    for _ in range(TICKS):
        world.step()
        if not world.living():
            break

    with open("events.json", "w") as f:
        json.dump(world.log, f, indent=1)

    counts = {}
    for e in world.log:
        counts[e["event"]] = counts.get(e["event"], 0) + 1

    print(f"=== {world.tick} ticks | {len(world.log)} events | {counts} ===\n")
    for a in agents:
        status = "alive" if a.alive else "DEAD "
        top = max(a.values, key=a.values.get)
        friends = sorted(a.affinity.items(), key=lambda x: -x[1])
        best = friends[0] if friends and friends[0][1] > 0 else None
        worst = friends[-1] if friends and friends[-1][1] < 0 else None
        print(f"{a.name:5} {status} hp={a.health:5.0f} $={a.money:5.1f} values:{top:6} "
              f"mem={len(a.memory.items):3}  friend={best[0] if best else '-':5} "
              f"enemy={worst[0] if worst else '-'}")

    a = max(agents, key=lambda x: len([m for m in x.memory.items if m.kind == "reflection"]))
    print(f"\n{a.name}'s strongest memories:")
    for m in a.memory.retrieve(world.tick, k=6):
        print(f"  t{m.tick:3} [{m.kind[:4]}] {m.text}")