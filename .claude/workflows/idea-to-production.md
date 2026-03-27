# Workflow: Idea to Production

The end-to-end journey from a raw idea to a feature live in production.

## Overview

```
Idea → Research → PRD → Architecture → Implementation → Testing → Deploy → Monitor
  │        │        │         │              │              │         │         │
  │   product-  product-  tech-lead-    plan_feature   run_tests  gitops   observability
  │   research  manager   architect                              /cicd      -infra
  └────────────────────────────────────────────────────────────────────────────────
```

## Phase 1: Discovery (Product)

**Goal:** Validate the problem is real and worth solving.

**Steps:**
1. Document the raw idea or user problem
2. Invoke `/generate-prd` to begin the research and requirements process
3. `product-research` agent: conduct user and market research
4. Align on problem statement (no solution yet)
5. Define success metrics with baselines

**Exit criteria:**
- [ ] Problem statement confirmed by stakeholders
- [ ] Target user segment defined with evidence
- [ ] Success metrics have baselines
- [ ] Decision: build vs buy vs defer

---

## Phase 2: Requirements (PRD)

**Goal:** Define exactly what to build, with clear acceptance criteria.

**Steps:**
1. `product-manager` agent: write PRD using research findings
2. Review all user stories and acceptance criteria
3. Resolve all open questions (no PRD with unknowns)
4. Get stakeholder sign-off on scope (P0 vs P1 vs P2)

**Artifacts:**
- `.claude/thoughts/prd/YYYY-MM-DD-[feature].md`

**Exit criteria:**
- [ ] PRD status: Approved
- [ ] All P0 requirements defined with acceptance criteria
- [ ] Out-of-scope section explicit
- [ ] Dependencies identified with owners and ETAs

---

## Phase 3: Technical Design

**Goal:** Design how to build it before writing any code.

**Steps:**
1. Invoke `/design-architecture` with the approved PRD
2. `tech-lead-architect` agent: produce Technical Design Document
3. Review API contract with frontend and backend leads
4. Review data model with DBA or backend lead
5. Identify and document technical risks with mitigations
6. Get tech lead sign-off on design

**Artifacts:**
- `.claude/thoughts/architecture/YYYY-MM-DD-[feature]-tdd.md`
- ADRs for key technical decisions (use `templates/architecture-decision-record.md`)

**Exit criteria:**
- [ ] TDD status: Approved
- [ ] API contract reviewed by both frontend and backend
- [ ] Data migration strategy defined (if applicable)
- [ ] Technical risks documented with mitigations
- [ ] Phase 1 scope clearly defined

---

## Phase 4: Implementation

**Goal:** Build the feature according to the TDD.

**Steps:**
1. Invoke `/plan-feature` with the approved TDD
2. Create implementation tasks from the plan
3. Backend: implement following clean architecture
   - Domain layer first (no external deps)
   - Infrastructure adapters second
   - HTTP handlers last
4. Frontend: implement following feature-based structure
   - API hooks first
   - State management second
   - UI components last
5. Write tests alongside code (TDD preferred)

**Key agents:**
- `go-architect` — structural decisions
- `concurrency` — goroutine patterns
- `fault-tolerance` — retry/circuit breaker
- `observability` — logging/metrics/tracing
- `frontend-architect` — component structure
- `state-management` — data flow

**Exit criteria:**
- [ ] All P0 features implemented
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Code reviewed (`/review-code`)
- [ ] golangci-lint passes

---

## Phase 5: Testing

**Goal:** Verify the implementation matches the PRD acceptance criteria.

**Steps:**
1. Invoke `/run-tests` — all test layers
2. Create test plan using `templates/test-plan-template.md`
3. Run E2E tests against staging environment
4. Performance test if SLO is involved
5. Manual QA against acceptance criteria in PRD
6. Fix any failures before proceeding

**Exit criteria:**
- [ ] All automated tests pass in CI
- [ ] Coverage meets targets (70% overall, 85% domain)
- [ ] All P0 acceptance criteria verified manually in staging
- [ ] Performance SLOs met in staging load test

---

## Phase 6: Deployment

**Goal:** Ship to production safely.

**Steps:**
1. Merge to main → CI runs → builds and pushes image
2. GitOps automation updates dev environment
3. Verify dev deployment is healthy
4. Create PR to staging GitOps overlay
5. Verify staging deployment is healthy
6. Create PR to prod GitOps overlay (requires approval)
7. Deploy to production during deployment window
8. Monitor for 30 minutes post-deployment

**Exit criteria:**
- [ ] Dev deployment healthy for 24 hours
- [ ] Staging deployment healthy, E2E tests pass
- [ ] Production deployment healthy for 30 minutes
- [ ] No spike in error rate or latency
- [ ] Rollback plan confirmed (revert GitOps commit)

---

## Phase 7: Monitor & Learn

**Goal:** Confirm the feature achieves its success metrics.

**Steps:**
1. Monitor error rates and latency for 48 hours
2. Track leading indicators (adoption, activation) at Day 7
3. Track lagging indicators (retention, NPS) at Day 30
4. Document learnings in `.claude/learnings.md`

**Exit criteria:**
- [ ] Primary metric on track to hit target
- [ ] No regression in counter-metrics
- [ ] Learnings documented for future features
