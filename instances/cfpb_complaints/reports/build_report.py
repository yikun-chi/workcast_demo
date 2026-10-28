"""Build instances/cfpb_complaints/reports/report.json from runs/cfpb_complaints/evaluation.json (orgsim.worlds.service.build_report).
Every number is read from the evaluation.

    uv run python instances/cfpb_complaints/reports/build_report.py
"""
from orgsim.instances import get_instance
from orgsim.worlds.service import build_report

if __name__ == "__main__":
    build_report(get_instance("cfpb_complaints"))
