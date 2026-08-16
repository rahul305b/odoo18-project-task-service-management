{
    'name': 'Project Task Service Management',
    'version': '18.0.1.2.0',
    'category': 'Services/Project',
    'summary': 'Customer-centric service fields on project.task: '
                'estimated time, billing mode, work sessions, time '
                'analysis, and employee/manager verification workflow.',
    'description': """
Project Task Service Management
================================

Extends the standard ``project.task`` model (via inheritance, no core
files modified) with fields needed for a customer-centric service
workflow:

* Estimated Time (distinct from Odoo's Allocated Time)
* Billing Mode (Hourly / Per Task)
* Verification Status (Not Started / In Progress / Waiting for
  Verification / Approved / Rejected)
* Employee Remarks / Manager Remarks
* Submitted By / Submitted On / Verified By / Verified On

It also introduces the ``project.task.work.session`` model, the
dedicated record of employee work periods that powers automatic time
tracking, plus Start / Pause / Resume actions so employees record
actual working time without manually entering hours.

Automatic time analysis (Variance to Finish, Remaining Time, Overrun)
is built entirely from Estimated Time and the Work Session records,
surfaced on the task form, the Timesheets tab, and the task list.

Finally, employees submit finished work with Done, and an authorized
manager (or the project's own Project Manager) Approves or Rejects it
- rejection returns the task to work without losing any prior work
sessions or time, and every submission cycle is preserved in a
``project.task.verification`` audit trail (see Verification History
tab).

Managers can also TRANSFER a task from one assigned employee to
another mid-flight (e.g. absence) via a wizard - the same task record
is kept, the outgoing employee's running session is closed as
'transferred' (never deleted), every other concurrently-working
employee is left untouched, and a permanent ``project.task.transfer``
audit record is created (see Transfer History tab).

Finally, an Administrator can designate a Project Manager (and
optional Additional Managers) per project, in terms of hr.employee.
This grants the "Project Task Service Manager" security group (never
Odoo Administrator rights) and, crucially, PROJECT-SPECIFIC
authorization: a manager of one project cannot approve/reject/
transfer tasks in a different project they were not assigned to
manage. Tasks also gain billing configuration (Billable flag, Hourly
Rate or Task Price, computed Billable Hours/Amount) built entirely on
top of the existing billing_mode and actual_work_hours - no
duplicate fields, no automatic invoicing.

A Manager Dashboard (Service Task Management > Service Task
Dashboard) rounds this out with read-only reporting built from
standard Odoo list/pivot/graph/search views: Task Performance (also
serving as the KPI summary via the pivot's own totals row), Pending
Manager Verification, Tasks Over Estimate, Billing Summary, a Work
Session Report (with pivot/graph analysis and a "Currently Working"
live view), and a Transfer Summary. Every figure is read directly
from fields already computed in earlier parts - nothing is
recalculated, and no data is duplicated into a separate reporting
model.

Finally, the whole workflow is wired into Odoo's own mail.activity
system: employees are notified when assigned or when a task is
transferred to/from them, the project's configured manager is
notified when a task is submitted for verification, and the
submitting employee is notified on approval or rejection (with the
manager's remarks included on rejection). One shared, lightweight
activity type is reused for all of these - no external email system,
no duplicate notification models, and DONE is now blocked outright
if a project has no configured manager to receive it (never silently
sent nowhere).

STATUS: Part 11 - final QA/hardening pass. No new business feature
and no workflow redesign, per that part's own scope. Two real defects
found and fixed during this pass (both are small, targeted changes,
not rewrites):

1. Concurrency: action_start_work/action_resume_work already had a
   row-level lock (Part 4/6) to prevent a double-click from creating
   two running sessions; this same protection was MISSING from
   action_submit_for_verification, action_approve_task,
   action_reject_task, and _transfer_task. A double-click on Done, in
   particular, could have created two project.task.verification
   records for the same submission. All four now take the same
   SELECT ... FOR UPDATE lock on the task row before validating state.

2. Security: the Work Session record rule for ordinary employees
   restricted write/create to their own sessions (Part 4) but left
   READ unrestricted for the whole project.group_project_user group -
   meaning any employee could browse every other employee's
   individual work-session history. Read is now scoped to "own
   sessions only" for that group, with a separate unrestricted-read
   rule added for project.group_project_manager so managers/dashboard
   reporting are unaffected.

Also added: an automated test suite (tests/test_project_task_service_
management.py) covering Start/Pause/Resume, one-active-session-per-
employee, Done/Approve/Reject and the reject-resubmit cycle, Transfer
(including optional reason and bystander-employee isolation), hourly
and per-task billing, Actual Time/Variance/Remaining/Overrun, and
every security-sensitive operation an employee must be blocked from.
    """,
    'author': 'Your Company',
    'website': '',
    'license': 'LGPL-3',
    'depends': [
        'project',
        'hr',
        'hr_timesheet',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/project_task_service_manager_groups.xml',
        'security/project_task_work_session_rules.xml',
        'security/project_task_verification_rules.xml',
        'data/mail_activity_type_data.xml',
        'views/project_task_views.xml',
        'views/project_task_work_session_views.xml',
        'views/project_task_timesheet_views.xml',
        'views/project_task_transfer_wizard_views.xml',
        'views/project_project_views.xml',
        'views/project_task_transfer_views.xml',
        'views/project_task_dashboard_views.xml',
        'views/project_task_dashboard_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
