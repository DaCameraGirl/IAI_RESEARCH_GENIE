# 25867 Remote Memory Transactions (Lossy Network)

Status: active
Category: Computer Science, Computer Engineering, Electrical Engineering,
Electronics Technology, Software Engineering
Study type: Prior art search (patent + non-patent literature)
Study patent: US7702742B2
Title: Mechanism for enabling memory transactions to be conducted across a
lossy network
Original assignee: Fortinet Inc (Woven Systems)
CPC class: G06F
Critical date: **2005-01-18** (latest date for responses)
Study patent priority: 2005-01-18

## Current focus (RWS leads)

**2026-06-22:** Single-reference ideal — combining locally originated memory
access / host-bus / I/O-bus transactions to a remote node; **priority-based
packetization and queuing**; **lossy Ethernet congestion drops**; **per-priority
sequencing, ACK/NACK and retransmission**.

**2026-06-16:** Sequencing per RR **1.8** in a network **designed** to drop
packets under congestion — not merely incidental loss.

**2026-06-08:** RR **1.7**, **1.8**, **1.13** — method on **Ethernet** (or
similar) that **drops packets when congested**.

## Problem statement

Distributed systems use multiple computing nodes on a network. One node (local)
must access memory controlled by another (remote). **Programmed I/O** maps
remote memory into the local physical address space; the local processor issues
**memory transaction messages (MTMs)** in the same processor bus protocol as
local memory access. A **network interface** encapsulates MTMs in network
packets and sends them across a **lossy network** (packets may be dropped;
order not guaranteed).

The study seeks prior art for a method/apparatus that ensures every MTM reaches
the remote node **in proper order** despite lossy delivery — via priority
queues, ordered send, per-priority sequencing, ACK/NACK, and retransmission.

## Research requirements

To satisfy, complete **8 priority** (5 optional):

### Core (1.1–1.8)

| Req | Summary |
|-----|---------|
| 1.1 | Receive MTMs from local memory controller; each MTM conforms to processor bus protocol for local processor/memory controller ↔ local memory |
| 1.2 | Determine MTMs destined for a particular remote node |
| 1.3 | Determine transaction type for each MTM |
| 1.4 | Compose network packet encapsulating at least a portion of each MTM |
| 1.5 | Assign sending priority per packet based on MTM transaction type + processor bus ordering rules |
| 1.6 | Organize packets into groups by sending priority |
| 1.7 | Send packets into **lossy network** in order determined by sending priorities |
| 1.8 | Ensure subset of packets with a particular sending priority received at remote node in **proper sequence** |

### Optional detail (1.9–1.13) — high value for current leads

| Req | Summary |
|-----|---------|
| 1.9 | MTM types: posted request, response, non-posted request → first, second, third sending priorities (posted highest) |
| 1.10 | First/second/third **queues** by priority; FIFO within queue; drain order: all first, then second, then third |
| 1.11 | If no ACK for a packet in subset → **resend that packet and all subsequent** in same subset, same order |
| 1.12 | Receive incoming packet → extract priority + sequence number → ACK + update expected sequence if match; else **drop** |
| 1.13 | Lossy network of 1.7 is **Ethernet** |

## Key figure anchors

- **Fig. 4:** Processor bus protocol ordering rules (posted / non-posted / response).
- **Fig. 6–9:** Network interface operation, per-priority queues, linked-lists of
  sent packets, ACK monitoring, retransmission on timeout.

## Lossy network bar (critical for 1.7 / 1.8 / 1.13)

RWS wants art where the network **purposefully drops** under congestion
(Ethernet switch drop behavior), not only best-effort links with incidental
loss. Highlights should name Ethernet congestion drop, QoS/priority queues,
sequence numbers, ACK/NACK, retransmit-on-gap.

## Submission rules

- Cross-check `known_art/known_citations.csv` (179 entries) before surfacing.
- Document date ≤ **2005-01-18**.
- Prefer **single reference** covering remote memory/bus transactions +
  priority queues + lossy Ethernet + per-priority sequencing/ACK/retransmit.
- Highlights verbatim; technical anchors: MTM, posted/non-posted, priority
  queue, sequence number, acknowledgement, retransmission, Ethernet, congestion
  drop.

## First search lanes

1. **Study NPL already burned** but useful mining: RDMA Consortium (Pinkerton
   SDP/iSER 2002–2003), DEC Memory Channel (Geweke 1999), SCI (Ryan 1998),
   TreadMarks, VM-based shared memory (Kontothanassis), TCP SACK/RFC 2581 —
   find **earlier or stronger** art not in CSV.
2. **Direct patent citations** in CSV: US5613071, US5936958, US6205498,
   US6230219, US6466580, US6678246, US6799220, US6970978, US7062609,
   US7185128, US2002/2003/2004 pub family — backward crawl ≤ 2005-01-18.
3. **Woven Systems / Fortinet** pre-2005 product literature, Wayback.
4. **Ethernet RDMA / iWARP / remote DMA** over lossy L2/L3 before 2005.
5. **Reflective memory / SCI / memory channel** — map carefully; proprietary
   non-Ethernet art may satisfy 1.1–1.8 but weak on 1.13 unless Ethernet
   called out.

## Known art

- CSV: `known_art/known_citations.csv`
- Summary: `known_art/KNOWN_CITATIONS.md`