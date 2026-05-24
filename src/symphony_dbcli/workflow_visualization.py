from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from textwrap import wrap

from .workflow_definition import WorkflowDefinitionConfig, WorkflowTransitionConfig

type NamedTransition = tuple[str, WorkflowTransitionConfig]


_NODE_WIDTH = 190
_NODE_HEIGHT = 92
_MARGIN_X = 24
_MARGIN_Y = 24
_COLUMN_GAP = 110
_ROW_GAP = 28
_DESCRIPTION_LINE_LIMIT = 29
_DESCRIPTION_LINE_COUNT = 2


@dataclass(frozen=True)
class WorkflowFlowNodeView:
    name: str
    description: str
    description_lines: tuple[str, ...]
    terminal: bool
    gate: str
    active_count: int
    x: int
    y: int
    width: int = _NODE_WIDTH
    height: int = _NODE_HEIGHT

    @property
    def left_center_x(self) -> int:
        return self.x

    @property
    def right_center_x(self) -> int:
        return self.x + self.width

    @property
    def center_y(self) -> int:
        return self.y + (self.height // 2)


@dataclass(frozen=True)
class WorkflowFlowEdgeView:
    name: str
    from_state: str
    to_state: str
    action: str
    trigger: str
    condition: str
    gate: str
    path: str
    label_x: int
    label_y: int
    backward: bool


@dataclass(frozen=True)
class WorkflowFlowchartView:
    width: int
    height: int
    initial_state: str
    nodes: list[WorkflowFlowNodeView]
    edges: list[WorkflowFlowEdgeView]

    @classmethod
    def from_definition(
        cls,
        workflow: WorkflowDefinitionConfig,
        *,
        state_counts: Mapping[str, int] | None = None,
    ) -> WorkflowFlowchartView:
        counts = state_counts or {}
        depths = _state_depths(workflow)
        columns = _columns(workflow, depths)
        nodes = _nodes(workflow, columns, counts)
        node_by_name = {node.name: node for node in nodes}
        edges = [
            _edge_view(name, transition, node_by_name, edge_index)
            for edge_index, (name, transition) in enumerate(workflow.transitions.items())
            if transition.from_state in node_by_name and transition.to_state in node_by_name
        ]
        width, height = _canvas_size(columns)
        return cls(
            width=width,
            height=height,
            initial_state=workflow.initial_state,
            nodes=nodes,
            edges=edges,
        )


def _state_depths(workflow: WorkflowDefinitionConfig) -> dict[str, int]:
    state_names = list(workflow.states)
    if not state_names:
        return {}
    initial_state = workflow.initial_state if workflow.initial_state in workflow.states else state_names[0]
    transitions_by_state = _transitions_by_state(workflow.transitions)
    max_depth = max(len(state_names) - 1, 0)
    depths: dict[str, int] = {initial_state: 0}

    def visit(state_name: str, visiting: set[str]) -> None:
        base_depth = depths[state_name]
        for _, transition in transitions_by_state.get(state_name, []):
            target = transition.to_state
            if target not in workflow.states or target in visiting:
                continue
            proposed_depth = min(base_depth + 1, max_depth)
            if proposed_depth > depths.get(target, -1):
                depths[target] = proposed_depth
                visit(target, visiting | {target})

    visit(initial_state, {initial_state})
    fallback_depth = max(depths.values(), default=0) + 1
    for state_name in state_names:
        depths.setdefault(state_name, fallback_depth)
    return depths


def _transitions_by_state(
    transitions: Mapping[str, WorkflowTransitionConfig],
) -> dict[str, list[NamedTransition]]:
    by_state: dict[str, list[NamedTransition]] = {}
    for name, transition in transitions.items():
        by_state.setdefault(transition.from_state, []).append((name, transition))
    return by_state


def _columns(
    workflow: WorkflowDefinitionConfig,
    depths: Mapping[str, int],
) -> dict[int, list[str]]:
    columns: dict[int, list[str]] = {}
    for state_name in workflow.states:
        columns.setdefault(depths.get(state_name, 0), []).append(state_name)
    return columns


def _nodes(
    workflow: WorkflowDefinitionConfig,
    columns: Mapping[int, list[str]],
    state_counts: Mapping[str, int],
) -> list[WorkflowFlowNodeView]:
    nodes: list[WorkflowFlowNodeView] = []
    for column, state_names in sorted(columns.items()):
        for row, state_name in enumerate(state_names):
            state = workflow.states[state_name]
            nodes.append(
                WorkflowFlowNodeView(
                    name=state_name,
                    description=state.description,
                    description_lines=_description_lines(state.description),
                    terminal=state.terminal,
                    gate=state.gate,
                    active_count=state_counts.get(state_name, 0),
                    x=_MARGIN_X + column * (_NODE_WIDTH + _COLUMN_GAP),
                    y=_MARGIN_Y + row * (_NODE_HEIGHT + _ROW_GAP),
                )
            )
    return nodes


def _edge_view(
    name: str,
    transition: WorkflowTransitionConfig,
    node_by_name: Mapping[str, WorkflowFlowNodeView],
    edge_index: int,
) -> WorkflowFlowEdgeView:
    source = node_by_name[transition.from_state]
    target = node_by_name[transition.to_state]
    start_x = source.right_center_x
    start_y = source.center_y
    end_x = target.left_center_x
    end_y = target.center_y
    backward = end_x <= start_x
    path, label_x, label_y = (
        _backward_edge_path(start_x, start_y, end_x, end_y, edge_index)
        if backward
        else _forward_edge_path(start_x, start_y, end_x, end_y)
    )
    return WorkflowFlowEdgeView(
        name=name,
        from_state=transition.from_state,
        to_state=transition.to_state,
        action=transition.action,
        trigger=transition.trigger,
        condition=transition.condition,
        gate=transition.gate,
        path=path,
        label_x=label_x,
        label_y=label_y,
        backward=backward,
    )


def _forward_edge_path(start_x: int, start_y: int, end_x: int, end_y: int) -> tuple[str, int, int]:
    curve = max(48, (end_x - start_x) // 2)
    path = f"M {start_x} {start_y} C {start_x + curve} {start_y} {end_x - curve} {end_y} {end_x} {end_y}"
    return path, (start_x + end_x) // 2, ((start_y + end_y) // 2) - 8


def _backward_edge_path(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    edge_index: int,
) -> tuple[str, int, int]:
    lane_y = max(start_y, end_y) + 64 + (edge_index % 3) * 18
    midpoint_x = (start_x + end_x) // 2
    path = (
        f"M {start_x} {start_y} "
        f"C {start_x + 56} {start_y} {start_x + 56} {lane_y} {midpoint_x} {lane_y} "
        f"C {end_x - 56} {lane_y} {end_x - 56} {end_y} {end_x} {end_y}"
    )
    return path, midpoint_x, lane_y - 8


def _canvas_size(columns: Mapping[int, list[str]]) -> tuple[int, int]:
    if not columns:
        return 320, 160
    column_count = max(columns) + 1
    row_count = max(len(states) for states in columns.values())
    width = (_MARGIN_X * 2) + (column_count * _NODE_WIDTH) + ((column_count - 1) * _COLUMN_GAP)
    height = (_MARGIN_Y * 2) + (row_count * _NODE_HEIGHT) + (max(row_count - 1, 0) * _ROW_GAP)
    return width, height


def _description_lines(text: str) -> tuple[str, ...]:
    value = " ".join(text.split())
    if not value:
        return ()
    return tuple(
        wrap(
            value,
            width=_DESCRIPTION_LINE_LIMIT,
            max_lines=_DESCRIPTION_LINE_COUNT,
            placeholder="...",
            break_long_words=False,
        )
    )
