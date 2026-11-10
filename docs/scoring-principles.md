# Scoring principles — how points work

The solver turns a seating problem into a single number and then maximises
it: a plan's score is the **sum of the points** its placements earn and lose
under the rules in force. This document is the contract for that arithmetic.
It is written for two readers at once: the implementer, who must know exactly
what a term may look like, and the operator, who must decide how many points
a rule is worth. Every principle below is a design decision, not an
implementation accident; where the engine does not yet provide a rule type
named here, the type is the work item — the principle already holds.

## 1. The model in one paragraph

**Hard rules are not points.** A hard rule bounds what is allowed at all —
it behaves as if it were worth infinite points and is implemented as a
constraint. If the hard rules conflict, the solve reports infeasibility and
names the conflict; it never buys its way out with points. Everything soft
is points, and **every point in the objective belongs to a rule the operator
added**. The engine contributes no opinions of its own: no hidden bonuses,
no built-in preferences. If a plan scores well, it is because the operator's
rules say so.

## 2. Rules are data, not code

The engine provides rule **types** (shapes with parameters). The operator
adds rule **instances** — a type, its parameters, its weight — through the
system's own UI/configuration, and can change or remove them without a code
change. A requested rule therefore never gets hard-coded: the development
work is always "support this rule type", never "bake this rule in". This
document describes types and their semantics; the instances live in the
event's data.

## 3. Every term scores one of three relations

Every scoring term belongs to exactly one class, named by the relation it
scores. When a new consideration appears, first ask which relation it is;
that decides where it belongs and what it may reference.

### 3.1 Intra-family — the family against itself

Concerns the family as a unit, regardless of anyone else.

- **Togetherness** — the family sits together (the atomic default: a family
  is placed whole unless a term below says otherwise).
- **Split penalty** — the family occupies more than one table. See §5.
- **Own-attribute grouping** — members sharing one of the family's own
  attributes (e.g. its youngsters) sit together within the family's
  placement.

### 3.2 Inter-family — the family against other families

Concerns pairs and sets of families, and exists only relative to a
criterion (§6).

- **Pair together / apart** — two named families share a table, or never do.
- **Attribute grouping across families** — guests sharing an attribute value
  (e.g. a language) earn pair points together, or lose points mixed (§4, §6).
- **Table-composition patterns** — a table's overall composition matches or
  violates a stated pattern.

### 3.3 Family vs venue — the family against the table and the room

Concerns where the family sits, regardless of who its neighbours are.

- **Zone placement** — a floor or area is preferred (or, in hard form,
  required).
- **Table-property needs** — a guest need matched by a table tag
  (e.g. `mobility=wheelchair` → `accessible`); see
  [table-properties.md](table-properties.md).
- **Capacity fit** — the family's size against the table's seats.
- **Fill / holes** — empty seats at a used table. See §7: the least
  important concern in the system.
- **Locked assignment (pin)** — the operator fixes a family to a table
  outright; a manual instruction, not a scored preference.

## 4. Polarity: two faces of the same coin

Every consideration can be framed **positively** — reward the desired
state — or **negatively** — penalise the undesired state. These are the
same coin, but they are not interchangeable: at the margins they behave
differently. A reward makes the good state worth points and leaves the bad
state merely unpaid; a penalty makes the bad state actively cost points,
which keeps pressure on even when the good state is out of reach. The
direction is therefore chosen deliberately for each rule type and stated
with it; the operator picks the direction again when adding a criterion
instance whose type supports both (§6).

Decided polarities:

| Term | Polarity | Unit |
| --- | --- | --- |
| Split penalty | Negative | per additional table |
| Holes | Negative | per empty seat |
| Combination criteria | Either — operator's choice per criterion | per pair |
| Zone / table fit | Positive | per preferred placement |

## 5. The split principle

Splitting a family is penalised at a **nearly-absolute** level: its weight
sits just below a hard rule. A family is split only when there is genuinely
no alternative — it exceeds the largest table it may use, or no feasible
whole placement exists — and then into the **fewest portions** possible.
The penalty is negative and **per additional table** (§4): a two-way split
and a six-way scatter are not the same failure, and the score must say so —
a flat "wholeness reward" would charge them identically.

Splitting needs no criterion. A family spread over several tables is
visible from the plan itself, so the split term is **structural**: it is
computed from the assignment, not from any attribute or operator-supplied
datum.

## 6. Mixing is criterion-born

There is **no context-free mixing penalty**, and none may be built. A
combination is "unwanted" only relative to a criterion the operator
supplies — for example, *speakers of a language sit with speakers of the
same language*. Without the criterion, two families sharing a table is just
a seating fact, not a defect. Unwanted mixing is therefore nothing more
than the **negative face of a criterion rule** (§4): desired combinations
earn, undesired ones cost. The engine's obligation is only that criterion
rule types support both directions.

## 7. Priority order

When concerns compete, they resolve in this order:

1. **Hard rules** — never violated, not points (§1).
2. **The split penalty** — nearly absolute (§5).
3. **Ordinary rule points** — the operator's preferences, traded off against
   each other by weight (§9).
4. **Holes** — empty seats are the least important problem in the system.
   A full house is never bought with a split: leaving seats empty is
   always preferable to breaking a family.

## 8. Low-priority families

A family can be marked **low-priority** — the mark is data, set through the
same configuration as any other rule (§2). A marked family is solved
**last**: everyone else is seated first, in the most convenient way, and
the marked family is then fitted into what remains. If it cannot be
placed, the solve does not fail silently: the interactive step presents
the operator with the concrete options for forcing it in (a free place, a
swap, a split, a chain move — the reassignment options) and asks which to
apply. The operator's choice is applied and persists as a manual
instruction, like a pin (§3.3).

## 9. How many points: sizing weights

Weights are **relative, not absolute**. A point has no meaning except
against the other points it competes with, so size a weight by what it
must override:

- **Size a penalty against the pool it must dominate.** A penalty that must
  always win has to exceed the total ordinary points at stake in a typical
  plan. That is what "nearly absolute" means in practice for the split
  weight: not a round number, but *more than everything else combined* can
  offer in exchange.
- **Per-unit terms scale with the damage.** Charge per additional table,
  per separated (or cross-criterion) pair, per empty seat — so a bigger
  failure costs proportionally more and the solver prefers the smaller
  failure on its own.
- **Keep ordinary weights on a small, consistent ladder** — e.g. 1 / 5 / 25
  for mild / normal / strong preferences — so the trade-offs between rules
  stay readable and two rules never collide by accident at an unintended
  ratio.
- **Holes get the smallest weight on the ladder** (§7): the fill term is a
  tie-breaker between otherwise-equal plans, nothing more.

## 10. Worked examples

### 10.1 The clan of 36 — why consolidation beats scatter

An upper floor holds four 14-seat tables and three 12-seat tables (92
seats). A 36-guest family, hard-restricted to this floor, exceeds every
table, so a split is unavoidable. Two candidate plans:

- **Scatter** (observed behaviour before this principle): portions of
  9 / 3 / 6 / 3 / 3 / 12 across six tables, mixed with other families on
  five of them.
- **Consolidated**: 12 / 12 / 12 on the three 12-seat tables, the family
  alone; the floor's other 56 guests pack exactly into the four 14-seat
  tables (8+4+2, 7+7, 5+5+4, 5+5+4), whole and unmixed among themselves no
  worse than before.

Let *W* be the split weight per additional table. The scatter occupies 6
tables → penalty 5*W*. The consolidation occupies 3 → penalty 2*W*. The
scatter must therefore find 3*W* more ordinary points than the
consolidation just to tie. But *W* is sized to exceed the entire ordinary
pool at stake on the floor (§9) — including every grouping point the
scatter could possibly pick up by mingling. No ordinary gain can cover
3*W*, so the consolidated plan wins on points, always. Under a
positive-only "wholeness reward" both plans would simply forfeit the same
reward, and the scatter's extra damage would be free — which is why the
split term is negative and per-table (§4, §5).

### 10.2 One criterion, two faces — language at a single table

Criterion instance supplied by the operator: *language*. One 8-seat table
holds a 7-guest Hebrew-speaking family and 1 Greek-speaking guest. Let *w*
be the per-pair weight.

- **Positive face** (reward same-language pairs seated together): the table
  earns C(7,2) = 21 of the 28 pair points a single-language table would
  earn. The mixed guest costs only the 7 pairs it does not form; the 7
  cross-language pairs that *do* form cost nothing.
- **Negative face** (penalise cross-language pairs): the table is charged
  7 × *w* — one for each Hebrew–Greek pair actually seated together.

Both faces prefer the unmixed table; they differ in what a mixed table
*pays*. Under the positive face, a mostly-uniform table keeps nearly all
its points and mixing is almost free at the margin. Under the negative
face, every mixed pair is an active cost, so the solver keeps hunting for
a cleaner arrangement. Which face applies is the operator's choice on the
criterion instance (§4, §6) — the engine's duty is to offer both.

### 10.3 A low-priority family that only fits by splitting

A family of 6 is marked low-priority (§8). Everyone else is seated first;
what remains is 4 free seats at one table and 2 at another, and no seated
family can be moved without breaking a hard rule. The family fits only as
a 4 + 2 split. The interactive step shows the operator exactly that: the
finished plan for everyone else, the two tables with their free seats
named, and the options — seat the family split 4 + 2 across those tables,
or leave it unseated. The operator picks the split; the choice is applied
and recorded as a manual instruction, so re-solving keeps it. The split
penalty (§5) still describes the cost honestly in the plan's score
breakdown — low priority changes the *order* of solving, not the
arithmetic.
