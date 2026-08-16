from odoo import _, api, fields, models


class ProjectTaskTransfer(models.Model):
    """Permanent audit record of a manager-initiated task transfer from
    one employee to another. Created exactly once per transfer by
    project.task._transfer_task() - never edited or deleted afterwards.
    """
    _name = 'project.task.transfer'
    _description = 'Project Task Transfer History'
    _order = 'transferred_at desc, id desc'

    task_id = fields.Many2one(
        comodel_name='project.task',
        string='Task',
        required=True,
        ondelete='cascade',
        index=True,
    )
    project_id = fields.Many2one(
        comodel_name='project.project',
        string='Project',
        related='task_id.project_id',
        store=True,
        index=True,
        readonly=True,
        help='Kept in sync from the task. Stored for the same reason '
             'as elsewhere in this module: search-view group_by '
             'contexts cannot use a dotted path (PART 9).',
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Customer',
        related='task_id.partner_id',
        store=True,
        index=True,
        readonly=True,
    )
    from_employee_id = fields.Many2one(
        comodel_name='hr.employee',
        string='From Employee',
        required=True,
        ondelete='restrict',
        help='Employee the task was transferred away from.',
    )
    to_employee_id = fields.Many2one(
        comodel_name='hr.employee',
        string='To Employee',
        required=True,
        ondelete='restrict',
        help='Employee the task was transferred to.',
    )
    transferred_by = fields.Many2one(
        comodel_name='res.users',
        string='Transferred By',
        required=True,
        readonly=True,
        ondelete='restrict',
        help='Manager/administrator who performed the transfer.',
    )
    transferred_at = fields.Datetime(
        string='Transferred At',
        required=True,
        readonly=True,
    )
    reason = fields.Text(
        string='Reason',
        required=False,
        help='Why the task was transferred, e.g. "Employee absent." '
             'Optional as of Part 8 (item 23) - a transfer must not be '
             'blocked just because no reason was given.',
    )
    reason_display = fields.Char(
        string='Reason',
        compute='_compute_reason_display',
        help='Same as Reason, but shows "-" instead of a blank cell '
             'when no reason was entered (Part 9, item 18) - used only '
             'in list/report display, never stored, never the actual '
             'data field.',
    )

    @api.depends('reason')
    def _compute_reason_display(self):
        for transfer in self:
            transfer.reason_display = transfer.reason.strip() if transfer.reason and transfer.reason.strip() else '-'

    # ------------------------------------------------------------------
    # PART 9: dashboard/reporting action. Same project-specific scoping
    # principle as elsewhere in this module (Part 8).
    # ------------------------------------------------------------------
    @api.model
    def _get_dashboard_domain_for_current_user(self):
        if self.env.user.has_group('base.group_system'):
            return []
        uid = self.env.user.id
        return [
            '|',
            ('project_id.user_id', '=', uid),
            ('project_id.project_manager_ids.user_id', '=', uid),
        ]

    @api.model
    def action_open_transfer_summary(self):
        """Menu: Service Task Dashboard > Transfer Summary. The record
        count Odoo already shows in the breadcrumb doubles as the
        "Number of Transfers" KPI from item 19 - no separate counter
        field needed.
        """
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfer Summary'),
            'res_model': 'project.task.transfer',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('project_task_service_management.view_project_task_transfer_list').id, 'list'),
                (False, 'form'),
            ],
            'search_view_id': [self.env.ref('project_task_service_management.view_project_task_transfer_search').id, 'search'],
            'domain': self._get_dashboard_domain_for_current_user(),
            'context': {},
        }
