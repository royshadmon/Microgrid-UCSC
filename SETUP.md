# Microgrid IEMS — Detailed Setup & Operations Guide

This document is the long-form companion to `INSTALL.md`. Read `INSTALL.md`
first if you have never deployed this system before; come here when you
need to understand a component in depth, run a non-default ingestion path,
recover from a failure, or onboard a new contributor.

This guide covers four things:

1. **Architecture** — what each of the eleven containers does and how
   they're wired together.
2. **Detailed deployment** — every step from a bare Mac to a fully
   running stack, with a verification at each step and a description
   of what success and failure look like.
3. **Local setup: ingestion alternatives** — three operationally complete
   paths for getting data from the eGauge meter into AnyLog (the
   current Kafka pipeline, a direct MQTT push, and a direct HTTP PUT),
   with rollback procedures for each.
4. **Operations** — daily checks, code updates, disaster recovery,
   troubleshooting reference.

---

## Table of contents

1. [Architecture](#1-architecture)
2. [Prerequisites](#2-prerequisites)
3. [Deployment](#3-deployment)
4. [Per-component reference](#4-per-component-reference)
5. [Local setup — ingestion alternatives](#5-local-setup--ingestion-alternatives)
6. [Cross-cutting health checks](#6-cross-cutting-health-checks)
7. [Operational runbook](#7-operational-runbook)
8. [Disaster recovery](#8-disaster-recovery)
9. [Troubleshooting reference](#9-troubleshooting-reference)
10. [File map](#10-file-map)

---

## 1. Architecture

### 1.1 The eleven containers

| Container | Image | Purpose | Ports |
|---|---|---|---|
| `postgres1` | postgres:14.0-alpine | Time-series store for all energy data | 5432 |
| `master` | anylogco/anylog-network:ucsc-arm | AnyLog metadata node (blockchain, policies) | 32048, 32049 |
| `operator1` | anylogco/anylog-network:ucsc-arm | AnyLog operator (writes to Postgres, hosts REST + TCP + MQTT broker) | 32148, 32149, 1883 |
| `kafka` | apache/kafka:3.9.2 | KRaft-mode broker, buffers eGauge messages | 9092, 9094 |
| `kafka-ui` | provectuslabs/kafka-ui:latest | Web inspector for Kafka topics | 8080 |
| `egauge-producer` | local build | Polls the eGauge meter, publishes to Kafka | — |
| `anylog-consumer` | local build | Fallback Kafka → AnyLog HTTP bridge | — |
| `ollama` | ollama/ollama:latest | Local LLM for DSS narrative | 11434 |
| `iems-app` | local build | FastAPI backend + React frontend | 8000, 3001 |
| `iems-inference` | local build | NILM ONNX disaggregator loop | — |
| `iems-dashboard` | local build | Zero-dep Node live dashboard | 47821 |