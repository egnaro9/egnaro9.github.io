#!/bin/bash
# claim-gate.sh — PreToolUse hook: DENY git commit/push that touch claim-bearing files
# until each changed file is accounted for in a review receipt.
#
# WHY: a memory instruction that can be skipped is not a control. On 2026-08-21 a false
# claim ("a fabricated quote is still served publicly") was published in a commit message
# because a stale note was trusted over the two files it named by line number. This gate
# forces the reviewer to name, per changed claim source, either an evidence pointer that
# RESOLVES or an override that is recorded.
#
# DETERMINISTIC BY DESIGN. It never decides whether a claim is true. It decides only:
#   (a) which changed files are claim-bearing, and
#   (b) whether every one of them is covered by a receipt line.
# Truth remains a human judgement; this enforces that the judgement happened.
#
# RECEIPT: .claim-review-ack in the repo root, one line per changed claim-bearing file:
#     <path> :: EVIDENCE <local-path-that-exists | https-url-returning-200>
#     <path> :: OVERRIDE <reason>
# EVIDENCE pointers are RESOLVED by this hook (file must exist; URL must return 2xx).
# OVERRIDE lines are allowed, printed loudly, and appended to .claim-review-audit.log.
#
# SCOPE: paths listed in .claim-paths (one glob per line). Missing file = built-in default.
# ROLLBACK: remove the PreToolUse entry from .claude/settings.json and delete this file.
# RESIDUAL: the receipt is agent-writable. This gate raises the cost of an unreviewed claim
# and leaves an audit trail; it is NOT a defence against a determined forger. The operator
# approval phrase remains the trust root.

REPO="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -z "$REPO" ] && exit 0

PAYLOAD=$(cat 2>/dev/null)
TOOL=$(printf '%s' "$PAYLOAD" | jq -r '.tool_name // ""' 2>/dev/null)
[ "$TOOL" != "Bash" ] && exit 0
CMD=$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.command // ""' 2>/dev/null)

# Fail-closed matcher: expose the leading token of every command segment.
NORM=$(printf '%s' "$CMD" | tr '()|;&`{}<>' '\n' | sed 's/^[[:space:]]*//' | sed -E 's/^([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)+//')
ACTION=""
printf '%s\n' "$NORM" | grep -qE '^git[[:space:]]+commit([[:space:]]|$)' && ACTION="commit"
printf '%s\n' "$NORM" | grep -qE '^git[[:space:]]+push([[:space:]]|$)'   && ACTION="push"
[ -z "$ACTION" ] && exit 0

cd "$REPO" 2>/dev/null || exit 0

if [ "$ACTION" = "commit" ]; then
    CHANGED=$(git diff --cached --name-only 2>/dev/null)
else
    CHANGED=$(git diff --name-only @{u}..HEAD 2>/dev/null)
fi
[ -z "$CHANGED" ] && exit 0

# Claim-bearing scope
if [ -f "$REPO/.claim-paths" ]; then
    PATTERNS=$(grep -v '^[[:space:]]*#' "$REPO/.claim-paths" | grep -v '^[[:space:]]*$')
else
    PATTERNS=$'index.html\n*.md\ndocs/*.json\nregistry.json\n*results*.json\n*manifest*.json\nsuite/*.html'
fi

MATCHED=""
while IFS= read -r f; do
    [ -z "$f" ] && continue
    while IFS= read -r p; do
        [ -z "$p" ] && continue
        case "$f" in $p) MATCHED="$MATCHED$f"$'\n'; break;; esac
        case "$(basename "$f")" in $p) MATCHED="$MATCHED$f"$'\n'; break;; esac
    done <<< "$PATTERNS"
done <<< "$CHANGED"
MATCHED=$(printf '%s' "$MATCHED" | grep -v '^$' | sort -u)
[ -z "$MATCHED" ] && exit 0

ACK="$REPO/.claim-review-ack"
MISSING="" ; UNRESOLVED="" ; OVERRIDES=""
while IFS= read -r f; do
    [ -z "$f" ] && continue
    LINE=$(grep -F -- "$f ::" "$ACK" 2>/dev/null | head -1)
    if [ -z "$LINE" ]; then MISSING="$MISSING  $f"$'\n'; continue; fi
    KIND=$(printf '%s' "$LINE" | sed -E 's/.*:: *([A-Z]+).*/\1/')
    REF=$(printf '%s' "$LINE" | sed -E 's/.*:: *[A-Z]+ *//')
    if [ "$KIND" = "OVERRIDE" ]; then
        OVERRIDES="$OVERRIDES  $f -> $REF"$'\n'
    elif [ "$KIND" = "EVIDENCE" ]; then
        if printf '%s' "$REF" | grep -qE '^https://'; then
            code=$(curl -s -o /dev/null -m 15 -w '%{http_code}' "$REF" 2>/dev/null)
            case "$code" in 2*) ;; *) UNRESOLVED="$UNRESOLVED  $f -> $REF (HTTP $code)"$'\n';; esac
        elif [ ! -e "$REF" ] && [ ! -e "$REPO/$REF" ]; then
            UNRESOLVED="$UNRESOLVED  $f -> $REF (no such path)"$'\n'
        fi
    else
        UNRESOLVED="$UNRESOLVED  $f -> malformed receipt line"$'\n'
    fi
done <<< "$MATCHED"

if [ -n "$OVERRIDES" ]; then
    printf '%s  %s OVERRIDE\n%s' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$ACTION" "$OVERRIDES" >> "$REPO/.claim-review-audit.log"
fi

if [ -n "$MISSING" ] || [ -n "$UNRESOLVED" ]; then
    REASON="CLAIM GATE: git $ACTION blocked. Claim-bearing files changed with no resolved review receipt."
    [ -n "$MISSING" ]    && REASON="$REASON"$'\n\nNo receipt line in .claim-review-ack for:\n'"$MISSING"
    [ -n "$UNRESOLVED" ] && REASON="$REASON"$'\nReceipt present but the evidence pointer did not resolve:\n'"$UNRESOLVED"
    REASON="$REASON"$'\nAdd one line per file to .claim-review-ack:\n  <path> :: EVIDENCE <existing-path-or-200-url>\n  <path> :: OVERRIDE <reason>\n\nEVIDENCE is resolved by this hook. Verify the claim against the artifact, not against a note.'
    jq -cn --arg r "$REASON" '{"decision":"block","reason":$r}'
    exit 0
fi
exit 0
