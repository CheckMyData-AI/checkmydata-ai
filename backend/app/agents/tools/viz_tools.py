"""Tool definitions available to the VizAgent."""

from app.llm.base import Tool, ToolParameter

RECOMMEND_VISUALIZATION_TOOL = Tool(
    name="recommend_visualization",
    description="Recommend the best visualization for the query results",
    parameters=[
        ToolParameter(
            name="viz_type",
            type="string",
            description="Visualization type",
            enum=["table", "bar_chart", "line_chart", "pie_chart", "scatter", "text", "number"],
        ),
        ToolParameter(
            name="config",
            type="string",
            description="JSON config for the visualization (labels, axes, colors, etc.)",
        ),
        ToolParameter(
            name="summary",
            type="string",
            description="Human-readable summary of the results",
        ),
    ],
)
