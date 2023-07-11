- Feature Name: specs_workflow
- Start Date: 10/07/20023
- RFC PR: https://gitlab.com/potato-oss/djangae/djangae/-/merge_requests/1403
- Issue: N/A

# Summary
Introduce a process to allow developers to submit RFCs, using git.

# Motivation
RFCs are a great too to create consensus over tech decisions and beyond.

A lot of times discussions happen in documents, calls, tickets, slack thread and generally get lost, together with their context.
Even when RFCs are used they are frequently kept outside of code versioning tools, and future developers don't have context of why specific decisions have been taken.

It's pretty common in the industry and specifically in Open Source to have RFCs versioned.
A documented workflow and templates would encourage Djangae mainters to use RFCs for Djangae.

# Guide-level explanation
Anytime new big feature, breaking changes, or big refactors are introduced, their motivation and suggested implementation should go through a more structure design process through the use of RFCs.

# Reference-level explanation
- Updated the contributing section with infornation over
    - When RFCs would be required
    - What would be the process to submit an RFC
- Create a template that can be re-used.

# Drawbacks
- It might introduce a bigger barrier for community to contribute?
- We'll the team quick enought to support the review of RFCs?


# Rationale and alternatives
N/A

# Prior art
In-code RFCs are a pretty common pattern. Our version has been highly inspired by the [Rust workflow](https://github.com/rust-lang/rfcs) in particular.

# Unresolved questions
- What happens to other OS packages that we maintain that are highly related to Djangae (e.g. connectors, emulators). Should they follow the same process? Let's try in Djangae first, and we'll see!

# Future possibilities
N/A
