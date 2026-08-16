from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ProjectProject(models.Model):
    """Extend project.project with a Primary Project Manager (and
    optional Additional Managers), expressed in terms of hr.employee -
    the vocabulary the rest of this module (Work Sessions, Verification,
    Transfer) already uses.

    Design: rather than maintaining a second, parallel "who manages
    this project" concept, project_manager_id is kept in sync with
    Odoo's own standard project.user_id ('Project Manager', a
    res.users field already used throughout core Project's own views,
    kanban cards, and reports). Setting project_manager_id
    automatically updates user_id to that employee's linked user, so
    the rest of standard Odoo keeps working exactly as any Odoo user
    would expect, while this module's authorization logic
    (project.task._is_user_authorized_manager_for_project) reads
    user_id as the primary-manager source of truth and
    project_manager_ids as the additional-managers list. This is a
    ONE-WAY sync (project_manager_id -> user_id); directly editing
    Odoo's own Project Manager field elsewhere does not update
    project_manager_id back.
    """
    _inherit = 'project.project'

    project_manager_id = fields.Many2one(
        comodel_name='hr.employee',
        string='Project Manager',
        help='Primary employee authorized to manage tasks in this '
             'project through this module: assign employees, transfer '
             'tasks, approve/reject verification submissions, and view '
             'billing information. Does NOT grant Odoo Administrator '
             'rights - only this module\'s manager permissions, and '
             'only for this specific project.',
    )
    project_manager_ids = fields.Many2many(
        comodel_name='hr.employee',
        relation='project_project_additional_manager_rel',
        column1='project_id',
        column2='employee_id',
        string='Additional Managers',
        help='Optional additional employees with the same manager '
             'permissions as the Project Manager, scoped to this '
             'project only. The Project Manager above remains the '
             'single, clearly-identified primary manager - this field '
             'is purely additive.',
    )

    @api.constrains('project_manager_id', 'project_manager_ids')
    def _check_project_managers_have_linked_user(self):
        for project in self:
            managers = project.project_manager_id | project.project_manager_ids
            for employee in managers:
                if not employee.user_id:
                    raise ValidationError(_(
                        'The selected project manager does not have a '
                        'linked Odoo user.'
                    ))

    # ------------------------------------------------------------------
    # Only an Administrator may configure who manages a project (item 30)
    # ------------------------------------------------------------------
    _MANAGER_PROTECTED_FIELDS = {'project_manager_id', 'project_manager_ids'}

    def write(self, vals):
        if self._MANAGER_PROTECTED_FIELDS.intersection(vals.keys()):
            if not self.env.user.has_group('base.group_system'):
                raise UserError(_(
                    'Only an Administrator can configure the Project '
                    'Manager for a project.'
                ))
        if 'project_manager_id' in vals:
            # Keep Odoo's own standard Project Manager (user_id) in
            # sync, one-way, so the rest of core Project keeps working
            # as expected - see the class docstring.
            vals = dict(vals)
            employee = (
                self.env['hr.employee'].browse(vals['project_manager_id'])
                if vals['project_manager_id'] else self.env['hr.employee']
            )
            vals['user_id'] = employee.user_id.id if employee.user_id else False
        res = super().write(vals)
        if self._MANAGER_PROTECTED_FIELDS.intersection(vals.keys()):
            self._grant_module_manager_group_to_project_managers()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """Enforces the same Administrator-only rule as write() for
        who may configure the Project Manager, applied here too since
        a project can have its manager set at creation time, not just
        via a later edit.

        Uses a truthy check (vals.get(...)) rather than "is the key
        present in vals", for the same reason as project.task.create():
        the web client's save payload typically includes every field
        shown on the form, including ones left at their empty default
        (project_manager_id/ids are empty by default) - a bare key-
        presence check would incorrectly require Administrator rights
        for creating an ordinary project that never touches these
        fields at all.
        """
        vals_list = [dict(v) for v in vals_list]
        for vals in vals_list:
            if vals.get('project_manager_id') or vals.get('project_manager_ids'):
                if not self.env.user.has_group('base.group_system'):
                    raise UserError(_(
                        'Only an Administrator can configure the '
                        'Project Manager for a project.'
                    ))
            if vals.get('project_manager_id'):
                employee = self.env['hr.employee'].browse(vals['project_manager_id'])
                if employee.user_id:
                    vals['user_id'] = employee.user_id.id
        projects = super().create(vals_list)
        if any(v.get('project_manager_id') or v.get('project_manager_ids') for v in vals_list):
            projects._grant_module_manager_group_to_project_managers()
        return projects

    def _grant_module_manager_group_to_project_managers(self):
        """Auto-provisioning (item 2: 'the employee should receive
        Project Manager permissions through our module'), rather than
        requiring an Administrator to separately go to Settings > Users
        and add the group by hand after picking a manager here.

        Only ADDS membership - it deliberately does not remove a user
        from the group if they stop being any project's manager, since
        safely detecting "no longer needed anywhere" would require
        scanning every project on every change. Documented as a known
        limitation; an Administrator can remove group membership
        manually via Settings > Users if needed.
        """
        group = self.env.ref(
            'project_task_service_management.group_project_task_service_manager',
            raise_if_not_found=False,
        )
        if not group:
            return
        users_to_add = self.mapped('project_manager_id.user_id') | \
            self.mapped('project_manager_ids.user_id')
        if users_to_add:
            group.sudo().write({'users': [(4, uid) for uid in users_to_add.ids]})

    # ------------------------------------------------------------------
    # Optional project-level billing defaults (item 19) - purely a
    # convenience for initializing new tasks; task-level fields always
    # take precedence once set, and changing these later never touches
    # existing tasks.
    # ------------------------------------------------------------------
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
        help="This project's company currency, used to display the "
             'default billing amounts below. Monetary fields require a '
             'currency_id on the same model, so this is defined '
             'explicitly here (related, not duplicated data) rather '
             'than assumed to already exist on project.project.',
    )
    default_billing_mode = fields.Selection(
        selection=[
            ('hourly', 'Hourly'),
            ('task', 'Per Task'),
        ],
        string='Default Billing Mode',
        help='Optional default used to initialize new tasks created '
             'under this project. Each task can still override this '
             'individually - changing this does not affect existing '
             'tasks.',
    )
    default_hourly_rate = fields.Monetary(
        string='Default Hourly Rate',
        currency_field='currency_id',
        help='Optional default hourly rate used to initialize new '
             'tasks created under this project when Default Billing '
             'Mode is Hourly.',
    )
    default_task_price = fields.Monetary(
        string='Default Task Price',
        currency_field='currency_id',
        help='Optional default fixed price used to initialize new '
             'tasks created under this project when Default Billing '
             'Mode is Per Task.',
    )
