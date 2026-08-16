from odoo import fields, models


class HrEmployee(models.Model):
    """Expose an employee's work-session history.

    PART 3 SCOPE: read-only reverse relation only - no computed totals
    here (per-task totals already live on project.task.actual_work_hours;
    duplicating a sum on hr.employee is deferred until there's a
    concrete reporting requirement for it).
    """
    _inherit = 'hr.employee'

    work_session_ids = fields.One2many(
        comodel_name='project.task.work.session',
        inverse_name='employee_id',
        string='Work Sessions',
        readonly=True,
        help='All work sessions recorded for this employee, across all '
             'tasks.',
    )
