---
name: vision-alignment
description: >
  Ensures all new features, user flows, and product decisions align with the product vision (vision.md).
  Use PROACTIVELY whenever planning new features, designing user behavior, proposing functionality changes,
  discussing product direction, creating user stories, writing specs, or making architectural decisions that
  affect the user experience. Also use when the user mentions "new feature", "add feature", "user flow",
  "user journey", "roadmap", "product decision", "what should we build", "prioritize", "user scenario",
  "behavior", "UX", or any planning/design discussion.
---

# Vision Alignment

Before planning any new feature, user flow, or product decision, read `vision.md` in the project root.

## When to Apply

- Planning or designing a new feature
- Proposing changes to existing user behavior or functionality
- Discussing product direction, priorities, or roadmap items
- Creating user stories, acceptance criteria, or specs
- Making architectural decisions that affect the user experience
- Reviewing PRs or features for product fit
- Answering "should we build X?" questions

## Process

1. Read `vision.md` to load the current vision context
2. Identify which vision layers the proposed work touches (Essence, Core Idea, System Behavior, User Role, System Nature, Invariants)
3. Evaluate alignment:
   - Does the feature match the system's described behavior (Layer 3)?
   - Does it respect the user/system role boundary (Layer 4)?
   - Does it preserve all invariants (Layer 7)?
   - Does it avoid the anti-vision (Layer 8)?
4. If misalignment is detected — trigger the Misalignment Resolution protocol below

## Misalignment Resolution

When a task does not align with the vision, do NOT silently reject or proceed. Ask the user explicitly.

### Step 1: Explain the conflict

Tell the user:
- What aspect of the task conflicts with the vision
- Which vision layer(s) and specific statements it contradicts (quote them)

### Step 2: Offer two options

> **Option A — Evolve the vision**: The task represents a legitimate strategic evolution. Update `vision.md` to accommodate the new direction, then proceed.
>
> **Option B — Adapt the task**: Keep the vision intact. Rework the task to fit within the existing vision.

### Step 3: Execute

- **Option A**: Update `vision.md` first, then proceed with the task.
- **Option B**: Propose a reworked version that aligns. Proceed after user confirms.

### When NOT to trigger

Do not ask for trivial or cosmetic changes that don't affect product direction. Only trigger when the task would meaningfully violate an invariant, contradict the anti-vision, or shift the system nature.

## Alignment Checklist

- [ ] Matches system behavior (Layer 3)
- [ ] Respects user/system boundary (Layer 4)
- [ ] Consistent with system nature (Layer 5)
- [ ] Delivers defined value (Layer 6)
- [ ] Preserves all invariants (Layer 7)
- [ ] Does not violate anti-vision (Layer 8)
- [ ] If any fails — Misalignment Resolution was triggered
