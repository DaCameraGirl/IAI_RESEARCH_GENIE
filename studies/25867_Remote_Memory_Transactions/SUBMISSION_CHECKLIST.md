# 25867 Submission Checklist

Critical date: **2005-01-18**

## Pre-submit gate

- [ ] Document date ≤ 2005-01-18
- [ ] Not in `known_art/known_citations.csv`
- [ ] Free downloadable PDF confirmed
- [ ] Not study patent US7702742 or listed family/citation

## Current RWS priority (2026-06-22 lead)

Ideal single reference discloses:

- [ ] Local memory / host-bus / I/O-bus transactions to **remote node**
- [ ] **Priority-based** packetization and **queuing**
- [ ] **Lossy Ethernet** with **congestion drops** (designed behavior)
- [ ] **Per-priority sequencing**, **ACK/NACK**, **retransmission**

Also high value: 1.7, 1.8, 1.13 together on congestion-drop Ethernet.

## Requirement mapping

| Req | Highlight must show |
|-----|---------------------|
| 1.1 | MTMs from memory controller; processor bus protocol |
| 1.2 | Destination = particular remote node |
| 1.3 | Transaction type per MTM |
| 1.4 | Network packet encapsulating MTM |
| 1.5 | Sending priority from transaction type + bus ordering rules |
| 1.6 | Groups/queues by sending priority |
| 1.7 | Send into **lossy** network in priority order |
| 1.8 | Per-priority **proper sequence** at remote node |
| 1.9 | Posted > response > non-posted priorities |
| 1.10 | Three queues; strict drain order |
| 1.11 | Resend packet + all subsequent in subset on missing ACK |
| 1.12 | Incoming: sequence match → ACK; else drop |
| 1.13 | Lossy network is **Ethernet** |

## Highlight quality

- [ ] Verbatim Ctrl+F in PDF
- [ ] Names congestion **drop** (not only generic packet loss)
- [ ] One sentence per requirement

## After submit

1. PDF → `submitted/`
2. Log in `CANDIDATE_SCREEN.md`
3. Update `_DASHBOARD.md`