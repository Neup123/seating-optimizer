"""Round-trip proof: printable list records are exact projections of the Plan."""
from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from seating_optimizer import (
    Assignment, Plan, Reason, TableUsage, render, render_people_list_html,
    render_table_list_html,
)
from seating_optimizer.api.app import app


def plan_fixture() -> Plan:
    return Plan(
        session_id='Dinner & friends',
        status='feasible',
        tables=[
            TableUsage(table_id='G1', zone_id='ground', capacity=4, occupied=2, empty_seats=2),
            TableUsage(table_id='G2', zone_id='ground', capacity=4, occupied=0, empty_seats=4),
            TableUsage(table_id='U1', zone_id='upper', capacity=3, occupied=1, empty_seats=2),
        ],
        assignments=[
            Assignment(
                group_id='family & <A>', table_id='G1',
                guest_ids=['a:1', 'a:2'], guest_names=['Alice & Bob', 'Bea <C>'],
                reasons=[Reason(rule_id='pref:1', description='Near a window & friends <X>', points=2),
                         Reason(rule_id='access', description='Needs accessibility', points=0)],
            ),
            Assignment(
                group_id='solo', table_id='U1',
                guest_ids=['b:1'], guest_names=['David'],
                reasons=[Reason(rule_id='zone:1', description='Upper floor preference', points=3)],
            ),
        ],
    )


def xml(html: str) -> ET.Element:
    assert '<script' not in html
    return ET.fromstring(html)


def expected_guests(plan: Plan) -> list[tuple[str, str, str, str, str]]:
    zones = {t.table_id: t.zone_id for t in plan.tables}
    return [(gid, name, entry.group_id, entry.table_id, zones[entry.table_id])
            for entry in plan.assignments
            for gid, name in zip(entry.guest_ids, entry.guest_names)]


@pytest.mark.parametrize('group_by', ['combined', 'floor'])
@pytest.mark.parametrize('include_reasons', [False, True])
def test_people_list_round_trips_all_plan_guests_and_exact_reasons(group_by, include_reasons):
    plan = plan_fixture()
    root = xml(render_people_list_html(plan, group_by=group_by, include_reasons=include_reasons))
    rows = root.findall('.//tr[@data-guest-id]')
    actual = [(r.attrib['data-guest-id'], r[0].text, r.attrib['data-group-id'],
               r.attrib['data-table-id'], r[4].text) for r in rows]
    assert actual == expected_guests(plan)
    if group_by == 'floor':
        assert [section.attrib['data-zone-id'] for section in root.findall('.//section')] == [
            'ground', 'upper']
        assert [len(s.findall('.//tr[@data-guest-id]')) for s in root.findall('.//section')] == [2, 1]
    else:
        assert len(root.findall('.//table')) == 1
    reasons = root.findall('.//p[@class="reason"]')
    if include_reasons:
        expected = [(reason.rule_id, reason.description)
                    for entry in plan.assignments
                    for _ in entry.guest_ids
                    for reason in entry.reasons]
        assert [(p.attrib['data-rule-id'], p.text) for p in reasons] == expected
    else:
        assert not reasons
        assert 'Written reasons' not in ''.join(root.itertext())


@pytest.mark.parametrize('group_by', ['combined', 'table'])
@pytest.mark.parametrize('include_reasons', [False, True])
def test_table_list_round_trips_all_plan_groups_and_exact_reasons(group_by, include_reasons):
    plan = plan_fixture()
    root = xml(render_table_list_html(plan, group_by=group_by, include_reasons=include_reasons))
    rows = root.findall('.//tr[@data-group-id]')
    expected = [(entry.group_id, entry.table_id, list(zip(entry.guest_ids, entry.guest_names)),
                 [(reason.rule_id, reason.description) for reason in entry.reasons])
                for table in plan.tables for entry in plan.assignments if entry.table_id == table.table_id]
    actual = [(r.attrib['data-group-id'], r.attrib['data-table-id'],
               [(person.attrib['data-guest-id'], person.text) for person in r.findall('.//span[@data-guest-id]')],
               [(reason.attrib['data-rule-id'], reason.text) for reason in r.findall('.//p[@class="reason"]')])
              for r in rows]
    assert [(g, t, people) for g, t, people, _ in actual] == [
        (g, t, people) for g, t, people, _ in expected]
    assert [reasons for _, _, _, reasons in actual] == [
        reasons if include_reasons else [] for _, _, _, reasons in expected]
    if group_by == 'table':
        assert [s.attrib['data-table-id'] for s in root.findall('.//section')] == ['G1', 'G2', 'U1']
        assert len(root.findall('.//table')) == 3
    else:
        assert len(root.findall('.//table')) == 1
    assert len(root.findall('.//tr[@class="empty"]')) == 1
    assert 'No assigned groups' in ''.join(root.itertext())


def test_export_registry_and_http_match_plan_without_mutating_it():
    plan = plan_fixture()
    before = plan.model_dump()
    assert render(plan, 'people-list-html') == render_people_list_html(plan)
    assert render(plan, 'table-list-html') == render_table_list_html(plan)
    client = TestClient(app)
    for endpoint, modes in [('people-list', ('combined', 'floor')),
                            ('table-list', ('combined', 'table'))]:
        for mode in modes:
            for reasons in (False, True):
                url = f'/v1/exports/{endpoint}/html'
                response = client.post(url, params={'group_by': mode, 'include_reasons': reasons},
                                       json=plan.model_dump(mode='json'))
                assert response.status_code == 200, response.text
                assert response.headers['content-type'].startswith('text/html')
                expected = (render_people_list_html if endpoint == 'people-list'
                            else render_table_list_html)(
                                plan, group_by=mode, include_reasons=reasons)
                assert response.text == expected
    assert plan.model_dump() == before


def test_list_export_rejects_nonfeasible_or_broken_plan_instead_of_dropping_assignments():
    plan = plan_fixture()
    plan.status = 'infeasible'
    with pytest.raises(ValueError, match='feasible'):
        render_people_list_html(plan)
    with pytest.raises(ValueError, match='feasible'):
        render_table_list_html(plan)
    plan.status = 'feasible'
    plan.assignments[0].guest_ids.pop()
    with pytest.raises(ValueError, match='Guest IDs and names'):
        render_people_list_html(plan)
    with pytest.raises(ValueError, match='Guest IDs and names'):
        render_table_list_html(plan)
    plan = plan_fixture()
    plan.assignments[0].table_id = 'nonexistent'
    with pytest.raises(ValueError, match='Unknown assigned table'):
        render_people_list_html(plan)
    with pytest.raises(ValueError, match='Unknown assigned table'):
        render_table_list_html(plan)
