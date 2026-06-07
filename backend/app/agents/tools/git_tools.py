"""Tool definitions available to the GitAgent.

Each tool maps 1:1 to a read-only ``GitInspector`` method. Numeric params are
clamped inside the inspector, so the schema only advertises sensible defaults.
"""

from app.llm.base import Tool, ToolParameter

GIT_LOG_TOOL = Tool(
    name="git_log",
    description=(
        "List recent commits (newest first). Optionally filter by file path(s), "
        "author, or a date range. Use this to understand recent code evolution."
    ),
    parameters=[
        ToolParameter(
            name="paths",
            type="array",
            description="Optional list of repo-relative file paths to filter commits by.",
            required=False,
            items={"type": "string"},
        ),
        ToolParameter(
            name="author",
            type="string",
            description="Optional author name/email substring filter.",
            required=False,
        ),
        ToolParameter(
            name="since",
            type="string",
            description="Optional start of range, e.g. '2024-01-01' or '30 days ago'.",
            required=False,
        ),
        ToolParameter(
            name="until",
            type="string",
            description="Optional end of range, e.g. '2024-03-01'.",
            required=False,
        ),
        ToolParameter(
            name="max_count",
            type="integer",
            description="Maximum number of commits to return (default 50).",
            required=False,
        ),
    ],
)

GIT_SHOW_TOOL = Tool(
    name="git_show",
    description=(
        "Show the full diff of a commit, or the content of a specific file at a "
        "given commit/ref. Provide 'path' to read a file's content at that revision."
    ),
    parameters=[
        ToolParameter(
            name="sha",
            type="string",
            description="Commit SHA, tag, or ref (e.g. 'HEAD', 'v1.2.0').",
        ),
        ToolParameter(
            name="path",
            type="string",
            description="Optional repo-relative file path to read at that revision.",
            required=False,
        ),
    ],
)

GIT_DIFF_TOOL = Tool(
    name="git_diff",
    description="Show the unified diff between two commits/refs, optionally scoped to paths.",
    parameters=[
        ToolParameter(name="a_sha", type="string", description="Base commit/ref."),
        ToolParameter(
            name="b_sha",
            type="string",
            description="Target commit/ref (default 'HEAD').",
            required=False,
        ),
        ToolParameter(
            name="paths",
            type="array",
            description="Optional list of repo-relative paths to scope the diff.",
            required=False,
            items={"type": "string"},
        ),
    ],
)

GIT_BLAME_TOOL = Tool(
    name="git_blame",
    description=(
        "Show per-line authorship for a file (who last changed each line). "
        "Useful to find who introduced a function or line of logic."
    ),
    parameters=[
        ToolParameter(
            name="path",
            type="string",
            description="Repo-relative file path to blame.",
        ),
        ToolParameter(
            name="commit_sha",
            type="string",
            description="Commit/ref to blame at (default 'HEAD').",
            required=False,
        ),
    ],
)

LIST_RELEASES_TOOL = Tool(
    name="list_releases",
    description=(
        "List release tags (newest first) with their commit SHA and date. "
        "Use this to build a release timeline for correlating with metrics."
    ),
    parameters=[
        ToolParameter(
            name="tag_prefix",
            type="string",
            description="Optional tag prefix filter (e.g. 'v' or 'release-').",
            required=False,
        ),
        ToolParameter(
            name="max_count",
            type="integer",
            description="Maximum number of releases to return (default 50).",
            required=False,
        ),
    ],
)

FILE_HISTORY_TOOL = Tool(
    name="file_history",
    description="List the commit history for a single file (newest first).",
    parameters=[
        ToolParameter(
            name="path",
            type="string",
            description="Repo-relative file path.",
        ),
        ToolParameter(
            name="max_count",
            type="integer",
            description="Maximum number of commits to return (default 50).",
            required=False,
        ),
    ],
)

WHO_CHANGED_TOOL = Tool(
    name="who_changed",
    description=(
        "Find commits whose diff added or removed a given text/regex pattern "
        "(git pickaxe). Useful to trace when a function or string was introduced."
    ),
    parameters=[
        ToolParameter(
            name="pattern",
            type="string",
            description="Text or regex to search for across diffs.",
        ),
        ToolParameter(
            name="case_sensitive",
            type="boolean",
            description="Whether the search is case-sensitive (default false).",
            required=False,
        ),
        ToolParameter(
            name="max_count",
            type="integer",
            description="Maximum number of commits to return (default 50).",
            required=False,
        ),
    ],
)

REVIEW_SIGNALS_TOOL = Tool(
    name="review_signals",
    description=(
        "Extract review-related signals from a commit message: Reviewed-by / "
        "Co-authored-by / Signed-off-by trailers, whether it is a merge commit, "
        "and any merged branch / pull-request reference."
    ),
    parameters=[
        ToolParameter(
            name="commit_sha",
            type="string",
            description="Commit SHA/ref to inspect.",
        ),
    ],
)

WRITE_CODE_NOTE_TOOL = Tool(
    name="write_code_note",
    description=(
        "Persist a durable finding about the codebase (e.g. 'function X uses a "
        "Redis cache for IP lookups') so it is remembered and surfaced in future "
        "questions. Use after you have studied code and want to record a fact."
    ),
    parameters=[
        ToolParameter(
            name="subject",
            type="string",
            description="What the note is about, e.g. 'path/to/file.py:function_name' or a SHA.",
        ),
        ToolParameter(
            name="note",
            type="string",
            description="The finding to remember (concise, factual).",
        ),
    ],
)


def get_git_tools() -> list[Tool]:
    """Return the read-only Git tools plus the code-note writer."""
    return [
        GIT_LOG_TOOL,
        GIT_SHOW_TOOL,
        GIT_DIFF_TOOL,
        GIT_BLAME_TOOL,
        LIST_RELEASES_TOOL,
        FILE_HISTORY_TOOL,
        WHO_CHANGED_TOOL,
        REVIEW_SIGNALS_TOOL,
        WRITE_CODE_NOTE_TOOL,
    ]
