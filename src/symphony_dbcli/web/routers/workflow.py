from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Request
from starlette.responses import Response

from symphony_dbcli.config import WorkflowError, render_workflow
from symphony_dbcli.web.dependencies import get_app_state, page_context, templates
from symphony_dbcli.workflow_edit import (
    CodexWorkflowEditModel,
    WorkflowEditProposal,
    parsed_config,
    propose_workflow_edit,
    propose_workflow_edit_with_model,
    validate_workflow_edit,
)
from symphony_dbcli.workflow_visualization import WorkflowFlowchartView

router = APIRouter(prefix="/workflow", tags=["workflow"])


@router.get("")
def index(request: Request) -> Response:
    app_state = get_app_state(request)
    workflow = app_state.config.workflow
    pending_gates = app_state.store.pending_workflow_gates(limit=20)
    workflow_history = app_state.store.workflow_history(limit=5)
    state_counts = app_state.store.workflow_state_counts()
    context = page_context(request, title="Workflow", active="workflow")
    context["workflow_chart"] = WorkflowFlowchartView.from_definition(
        workflow,
        state_counts=state_counts,
        orientation="vertical",
    )
    context["state_count"] = len(workflow.states)
    context["transition_count"] = len(workflow.transitions)
    context["automatic_count"] = sum(
        1 for transition in workflow.transitions.values() if transition.trigger == "automatic"
    )
    context["human_gate_count"] = sum(
        1 for transition in workflow.transitions.values() if transition.trigger == "human"
    )
    context["states"] = workflow.states.items()
    context["transitions"] = workflow.transitions.items()
    context["pending_gates"] = pending_gates
    context["workflow_history"] = workflow_history
    return templates.TemplateResponse(
        request=request,
        name="workflow/index.html",
        context=context,
    )


@router.get("/edit")
def edit(request: Request) -> Response:
    current = _workflow_content(request)
    proposal = validate_workflow_edit(current, current, "")
    return templates.TemplateResponse(
        request=request,
        name="workflow/edit.html",
        context=_edit_context(request, proposal, applied=False),
    )


@router.post("/edit")
def update(
    request: Request,
    action: Annotated[str, Form()] = "preview",
    workflow_request: Annotated[str, Form(alias="request")] = "",
    proposed_content: Annotated[str, Form()] = "",
) -> Response:
    current = _workflow_content(request)
    if action == "generate":
        state = get_app_state(request)
        workflow_dir = Path(state.workflow_path).resolve().parent
        proposal = propose_workflow_edit_with_model(
            current,
            workflow_request,
            model=CodexWorkflowEditModel(state.config, workflow_dir),
        )
    else:
        proposal = (
            validate_workflow_edit(current, proposed_content, workflow_request)
            if proposed_content
            else propose_workflow_edit(current, workflow_request)
        )
    if action == "apply" and proposal.valid:
        try:
            config = parsed_config(proposal.proposed_content)
        except WorkflowError as exc:
            proposal = validate_workflow_edit(
                current,
                proposal.proposed_content,
                f"{workflow_request}\n{exc}",
            )
            return templates.TemplateResponse(
                request=request,
                name="workflow/edit.html",
                context=_edit_context(request, proposal, applied=False),
            )
        state = get_app_state(request)
        Path(state.workflow_path).write_text(proposal.proposed_content, encoding="utf-8")
        state.store.record_workflow_version(state.workflow_path, proposal.proposed_content, config)
        request.app.state.symphony = replace(state, config=config)
        return templates.TemplateResponse(
            request=request,
            name="workflow/edit.html",
            context=_edit_context(request, proposal, applied=True),
        )
    return templates.TemplateResponse(
        request=request,
        name="workflow/edit.html",
        context=_edit_context(request, proposal, applied=False),
    )


def _edit_context(
    request: Request,
    proposal: WorkflowEditProposal,
    *,
    applied: bool,
) -> dict[str, object]:
    context = page_context(request, title="Workflow Editor", active="workflow")
    context["proposal"] = proposal
    context["applied"] = applied
    context["workflow_chart"] = _workflow_chart_for_proposal(proposal)
    return context


def _workflow_chart_for_proposal(proposal: WorkflowEditProposal) -> WorkflowFlowchartView | None:
    if not proposal.valid:
        return None
    try:
        return WorkflowFlowchartView.from_definition(
            parsed_config(proposal.proposed_content).workflow,
            orientation="vertical",
        )
    except WorkflowError:
        return None


def _workflow_content(request: Request) -> str:
    state = get_app_state(request)
    path = Path(state.workflow_path)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return render_workflow(state.config)
