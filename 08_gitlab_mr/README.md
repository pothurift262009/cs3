# 09 — GitLab Merge Request

**Deliverable:** evidence of the feature branch, commits, MR description and peer review.

## Required in the MR description

- **What changed**
- **Why**
- **What was tested**
- **How to verify the result**

## Checks before you open it

- [ ] Meaningful commit messages — one logical change each, not `update` x12
- [ ] **No secrets**: no connection strings, account identifiers, keys or `.env`
- [ ] `data/` is gitignored and no 80 MB CSV is in the history
      (`git log --stat | sort -k3 -n | tail` to confirm nothing huge slipped in)
- [ ] `_answer_key/` and `truth_manifest.md` are not committed
- [ ] Peer review evidence attached (comments, approval)

## If a large file was already committed

Removing it from the working tree does not remove it from history. Rewrite the
branch with `git filter-repo` or start a clean branch and cherry-pick the code.
