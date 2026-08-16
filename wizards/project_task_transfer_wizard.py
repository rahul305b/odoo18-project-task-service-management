from odoo import api, fields, models


class ProjectTaskTransferWizard(models.TransientModel):
    """Manager-facing wizard for TRANSFER TASK. Collects which currently-
    assigned employee the work is coming FROM and which employee it is
    going TO, plus an optional reason (Part 8, item 23 - a reason must
    never block a transfer), then delegates the actual state changes to
    project.task._transfer_task() so all the business rules
    (running-session closing, assignee update, history record) live in
    one place and can be re-used/tested independently of this wizard.
    """
    _name = 'project.task.transfer.wizard'
    _description = 'Transfer Task Wizard'

    task_id = fields.Many2one(
        comodel_name='project.task',
        string='Task',
        required=True,
        readonly=True,
    )
    assigned_employee_ids = fields.Many2many(
        comodel_name='hr.employee',
        compute='_compute_assigned_employee_ids',
        help='Employees currently assigned to the task (derived from '
             "the task's own assignee field) - used only to restrict "
             'the From Employee selection below to people actually on '
             'the task.',
    )
    from_employee_id = fields.Many2one(
        comodel_name='hr.employee',
        string='Current Employee',
        required=True,
        help='The currently-assigned employee whose work is being '
             'transferred away. Must be explicitly chosen - the wizard '
             'never assumes which assignee this is when a task has '
             'several.',
    )
    to_employee_id = fields.Many2one(
        comodel_name='hr.employee',
        string='Transfer To',
        required=True,
        help='The employee who will continue this task.',
    )
    reason = fields.Text(
        string='Reason',
        required=False,
        help='Why this task is being transferred, e.g. "Employee is '
             'absent today." Optional (Part 8, item 23) - stored '
             'permanently in the transfer history when given, but '
             'never required. Separate from Employee Remarks and '
             'Manager Remarks.',
    )

    @api.depends('task_id', 'task_id.user_ids')
    def _compute_assigned_employee_ids(self):
        Employee = self.env['hr.employee']
        for wizard in self:
            if wizard.task_id and wizard.task_id.user_ids:
                wizard.assigned_employee_ids = Employee.search([
                    ('user_id', 'in', wizard.task_id.user_ids.ids),
                ])
            else:
                wizard.assigned_employee_ids = Employee

    @api.onchange('task_id')
    def _onchange_task_id_suggest_from_employee(self):
        """Pure UX convenience: if only one employee is currently
        assigned, pre-select them as the outgoing employee so the
        manager doesn't have to pick the obvious answer. With multiple
        assignees, nothing is pre-selected - the manager must choose
        explicitly, per the Part 7 spec.
        """
        for wizard in self:
            if wizard.task_id and len(wizard.assigned_employee_ids) == 1:
                wizard.from_employee_id = wizard.assigned_employee_ids

    def action_transfer(self):
        self.ensure_one()
        self.task_id._transfer_task(
            from_employee=self.from_employee_id,
            to_employee=self.to_employee_id,
            reason=self.reason,
        )
        return {'type': 'ir.actions.act_window_close'}
