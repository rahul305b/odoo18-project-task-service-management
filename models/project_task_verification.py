from odoo import fields, models


class ProjectTaskVerification(models.Model):
    """One record per employee submission ('Done' click) of a task for
    manager verification.

    Why this model exists: project.task's own submitted_by/submitted_on/
    verified_by/verified_on/manager_remarks fields (reused from Part 2)
    can only ever hold the LATEST verification cycle - each new
    submission or verification overwrites them. Since a task can be
    submitted, rejected, and resubmitted multiple times (Part 6, items
    18-19), and the spec explicitly requires that history survive
    (Test 5: "Previous rejection remains in history"), a separate
    append-only model is needed. Records here are never deleted or
    overwritten - action_submit_for_verification() creates a new one
    each time, and action_approve_task()/action_reject_task() only
    update the single most recent 'waiting' record.
    """
    _name = 'project.task.verification'
    _description = 'Project Task Verification History'
    _order = 'submitted_at desc, id desc'

    task_id = fields.Many2one(
        comodel_name='project.task',
        string='Task',
        required=True,
        ondelete='cascade',
        index=True,
    )
    employee_id = fields.Many2one(
        comodel_name='hr.employee',
        string='Employee',
        required=True,
        ondelete='restrict',
        help='Employee who submitted this verification cycle.',
    )
    submitted_by = fields.Many2one(
        comodel_name='res.users',
        string='Submitted By',
        required=True,
        readonly=True,
        ondelete='restrict',
    )
    submitted_at = fields.Datetime(
        string='Submitted At',
        required=True,
        readonly=True,
    )
    employee_remarks = fields.Text(
        string='Employee Remarks',
        readonly=True,
        help='Snapshot of the employee remarks at the moment of this '
             'submission.',
    )
    verified_by = fields.Many2one(
        comodel_name='res.users',
        string='Verified By',
        readonly=True,
    )
    verified_at = fields.Datetime(
        string='Verified At',
        readonly=True,
    )
    manager_remarks = fields.Text(
        string='Manager Remarks',
        readonly=True,
    )
    result = fields.Selection(
        selection=[
            ('waiting', 'Waiting for Verification'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        string='Result',
        default='waiting',
        required=True,
        readonly=True,
    )
