# sysadmin-ai Testing Pipeline — Master Plan

**Objective:** Create an automated, ephemeral testing pipeline that validates sysadmin-ai behavior across diverse operating systems using real VMs to ensure systemd, package managers, and kernel-level commands function correctly where Docker fails.

---

## Phase 1: The Infrastructure Controller (Python)

**Goal:** Abstract the DigitalOcean API into a Python class that manages the lifecycle of a test instance.

---

## Phase 2: The SSH & Deployment Driver

**Goal:** Automate the transfer of sysadmin-ai to the remote server and prepare the environment.

---

## Phase 3: The OS Matrix Strategy

**Goal:** Define the exact targets to prove cross-distro compatibility.

---

## Phase 4: Integration (The Test Suite)

**Goal:** Wrap the infrastructure and deployment into standard test disciplines.

---

## Phase 5: Cost & Safety Guardrails

**Goal:** Prevent accidental billing spikes.
