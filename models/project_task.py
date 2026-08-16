import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    """Extend project.task with the fields needed for the customer-centric
    service workflow (estimated time, billing mode, verification status,
    and the audit trail of who submitted/verified the task).

    PART 2 SCOPE:
    - Fields only. No buttons, no state-changing methods, no overridden
      create()/write(), no timer, no transfer, no invoicing.
    - The existing Task Code customization on this model is left
      completely untouched; it is not referenced here.
    """
    _inherit = 'project.task'

    # ------------------------------------------------------------------
    # Estimated time (distinct from Odoo's own allocated_hours)
    # ------------------------------------------------------------------
    estimated_time = fields.Float(
        string='Estimated Time',
        help='Expected time (in hours) required to complete this task, '
             'as entered by the manager. This is independent from '
             "Odoo's own Allocated Time field, which is left untouched.",
    )

    # ------------------------------------------------------------------
    # Billing
    # ------------------------------------------------------------------
    billing_mode = fields.Selection(
        selection=[
            ('hourly', 'Hourly'),
            ('task', 'Per Task'),
        ],
        string='Billing Mode',
        default='hourly',
        help='Whether the customer is billed based on actual employee '
             'time worked (Hourly) or a fixed amount for the task '
             '(Per Task). Invoicing logic is not implemented yet.',
    )

    # ------------------------------------------------------------------
    # PART 8: billing configuration and calculation, built on top of
    # the existing billing_mode (Part 2) and actual_work_hours (Part 3)
    # - neither is duplicated here.
    # ------------------------------------------------------------------
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='project_id.company_id.currency_id',
        store=True,
        readonly=True,
        help="This task's company currency (via its project), used for "
             'the Monetary fields below. Routed through project_id '
             'rather than assuming project.task has its own company_id '
             'field.',
    )
    is_billable = fields.Boolean(
        string='Billable',
        default=True,
        help='Whether this task should be billed to the customer at '
             'all. When unchecked, Billable Amount is always 0 '
             'regardless of billing mode/rate/price - actual time is '
             'still tracked normally for internal productivity and '
             'variance reporting.',
    )
    hourly_rate = fields.Monetary(
        string='Hourly Rate',
        currency_field='currency_id',
        help='Rate charged per hour of actual work, used when Billing '
             'Mode is Hourly. Ignored when Billing Mode is Per Task.',
    )
    task_fixed_price = fields.Monetary(
        string='Task Price',
        currency_field='currency_id',
        help='Fixed amount charged for this task regardless of actual '
             'hours worked, used when Billing Mode is Per Task. '
             'Ignored when Billing Mode is Hourly.',
    )
    billable_hours = fields.Float(
        string='Billable Hours',
        compute='_compute_billable_hours',
        store=True,
        help='For Hourly billing, equals Actual Work Hours. For Per '
             'Task billing this is informational only (it does not '
             'drive Billable Amount, which is the fixed Task Price '
             'instead) - kept at 0 to avoid implying actual time '
             'affects the fixed customer price.',
    )
    billable_amount = fields.Monetary(
        string='Billable Amount',
        compute='_compute_billable_amount',
        store=True,
        currency_field='currency_id',
        help='Informational billing figure for this task - NOT an '
             'invoice and no accounting entries are created from it. '
             '0 if not Billable. Otherwise: actual_work_hours * '
             'hourly_rate for Hourly billing, or task_fixed_price for '
             'Per Task billing. Uses standard Odoo Monetary rounding '
             'for the task/project company currency.',
    )

    @api.depends('billing_mode', 'actual_work_hours')
    def _compute_billable_hours(self):
        for task in self:
            task.billable_hours = (
                task.actual_work_hours if task.billing_mode == 'hourly' else 0.0
            )

    @api.depends('is_billable', 'billing_mode', 'actual_work_hours',
                 'hourly_rate', 'task_fixed_price')
    def _compute_billable_amount(self):
        for task in self:
            if not task.is_billable:
                task.billable_amount = 0.0
            elif task.billing_mode == 'hourly':
                task.billable_amount = task.actual_work_hours * task.hourly_rate
            elif task.billing_mode == 'task':
                task.billable_amount = task.task_fixed_price
            else:
                task.billable_amount = 0.0

    @api.onchange('project_id')
    def _onchange_project_id_apply_billing_defaults(self):
        """Convenience only (Part 8, item 19): if the project has
        default billing settings AND this task's own billing fields
        are still untouched (still at their field defaults), pre-fill
        from the project. Never overwrites values a manager has
        already customized on this task - the moment any of these
        fields differs from its default, this onchange stops touching
        it for the rest of that field's lifetime on this task (it only
        runs again if project_id itself is changed again).
        """
        for task in self:
            project = task.project_id
            if not project:
                continue
            # Heuristic for "still untouched": both monetary fields are
            # still at 0. billing_mode itself has no natural "unset"
            # value (it defaults to 'hourly'), so this monetary check
            # is the more reliable signal that nothing has been
            # customized on this task yet.
            still_untouched = not task.hourly_rate and not task.task_fixed_price
            if still_untouched and project.default_billing_mode:
                task.billing_mode = project.default_billing_mode
            if not task.hourly_rate and project.default_hourly_rate:
                task.hourly_rate = project.default_hourly_rate
            if not task.task_fixed_price and project.default_task_price:
                task.task_fixed_price = project.default_task_price

    # ------------------------------------------------------------------
    # Verification workflow status (separate from Odoo's stage_id)
    # ------------------------------------------------------------------
    verification_status = fields.Selection(
        selection=[
            ('not_started', 'Not Started'),
            ('in_progress', 'In Progress'),
            ('waiting', 'Waiting for Verification'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        string='Verification Status',
        default='not_started',
        help='Business verification state for this task, tracked '
             "separately from Odoo's own task stage. Driven by the "
             'Start / Done / Approve / Reject actions (Parts 4 and 6).',
    )

    # ------------------------------------------------------------------
    # Employee-facing remarks
    # ------------------------------------------------------------------
    employee_remarks = fields.Text(
        string='Employee Remarks',
        help='Explanation from the employee for delays, blockers, or '
             'incomplete customer-provided information, especially when '
             'the task took longer than estimated.',
    )

    # ------------------------------------------------------------------
    # Submission audit trail
    # ------------------------------------------------------------------
    submitted_by = fields.Many2one(
        comodel_name='res.users',
        string='Submitted By',
        readonly=True,
        help='User who submitted this task for manager verification.',
    )
    submitted_on = fields.Datetime(
        string='Submitted On',
        readonly=True,
        help='Date/time the task was submitted for manager verification.',
    )

    # ------------------------------------------------------------------
    # Verification audit trail
    # ------------------------------------------------------------------
    verified_by = fields.Many2one(
        comodel_name='res.users',
        string='Verified By',
        readonly=True,
        help='Manager who approved or rejected this task.',
    )
    verified_on = fields.Datetime(
        string='Verified On',
        readonly=True,
        help='Date/time the manager verified (approved or rejected) '
             'this task.',
    )
    rejection_reason = fields.Text(
        string='Rejection Reason (Deprecated)',
        help='Deprecated as of Part 6 - superseded by manager_remarks, '
             'which covers both approve and reject explanations. Kept '
             'only so no data already stored here is lost; new logic '
             'does not read or write this field.',
    )

    # ------------------------------------------------------------------
    # PART 6: Manager remarks (covers both Approve and Reject)
    # ------------------------------------------------------------------
    # A new field rather than repurposing rejection_reason: that field's
    # technical name would be actively misleading once it also stores
    # approval remarks, and Part 6 needs one field for both cases per
    # its own spec ("manager_remarks... approved/rejected").
    manager_remarks = fields.Text(
        string='Manager Remarks',
        help='Explanation from the manager for approving or rejecting '
             'this submission. Required when rejecting; optional when '
             'approving. Kept separate from Employee Remarks - one '
             'never overwrites the other.',
    )
    verification_history_ids = fields.One2many(
        comodel_name='project.task.verification',
        inverse_name='task_id',
        string='Verification History',
        readonly=True,
        help='One record per DONE submission, permanently preserved '
             'even across multiple reject/resubmit cycles. The fields '
             'above (Verification Status, Submitted By/On, Verified '
             'By/On, Manager Remarks) always reflect only the latest '
             'cycle; this list is the full audit trail.',
    )

    # ------------------------------------------------------------------
    # PART 3: Work session integration
    # ------------------------------------------------------------------
    work_session_ids = fields.One2many(
        comodel_name='project.task.work.session',
        inverse_name='task_id',
        string='Work Sessions',
        readonly=True,
        help='All work sessions (running, paused, completed, '
             'transferred or cancelled) recorded against this task. '
             'This is the source of truth for actual time worked - it '
             'is not derived from Timesheets.',
    )
    actual_work_hours = fields.Float(
        string='Actual Work Hours',
        compute='_compute_actual_work_hours',
        store=True,
        help='Total hours actually worked on this task, summed from '
             'all closed work sessions (Completed, Paused, '
             'Transferred). Running and Cancelled sessions are '
             'excluded. This is independent from Odoo\'s own '
             'Timesheets and from Estimated Time / Allocated Time.',
    )
    active_work_session_id = fields.Many2one(
        comodel_name='project.task.work.session',
        string='Active Work Session',
        compute='_compute_active_work_session_id',
        help='The currently running work session on this task, if '
             'any. Empty if no employee currently has this task '
             'running.',
    )

    @api.depends('work_session_ids.duration', 'work_session_ids.state')
    def _compute_actual_work_hours(self):
        counted_states = ('completed', 'paused', 'transferred')
        for task in self:
            task.actual_work_hours = sum(
                session.duration
                for session in task.work_session_ids
                if session.state in counted_states
            )

    @api.depends('work_session_ids.state')
    def _compute_active_work_session_id(self):
        for task in self:
            running = task.work_session_ids.filtered(
                lambda s: s.state == 'running'
            )
            # Defensive: business rule says at most one, but Part 3
            # does not yet enforce that at the database level (see
            # note in project_task_work_session.py), so guard against
            # more than one existing during testing.
            task.active_work_session_id = running[:1]

    # ------------------------------------------------------------------
    # PART 5: Time analysis (variance, remaining, overrun)
    # ------------------------------------------------------------------
    # These all build on the existing estimated_time (Part 2) and
    # actual_work_hours (Part 3) fields - no duplicate "estimated" or
    # "actual" field is introduced here.

    variance_to_finish = fields.Float(
        string='Variance to Finish',
        compute='_compute_time_analysis',
        store=True,
        help='estimated_time - actual_work_hours. Positive means the '
             'task is still within its estimate; zero means exactly at '
             'estimate; negative means the estimate has been exceeded. '
             'The sign is meaningful and is never converted to an '
             'absolute value.',
    )
    remaining_estimated_hours = fields.Float(
        string='Remaining Time',
        compute='_compute_time_analysis',
        store=True,
        help='How much of the estimated time is still available: '
             'max(estimated_time - actual_work_hours, 0). Unlike '
             'Variance to Finish, this never goes negative - once the '
             'estimate is exceeded it simply reads 0.',
    )
    overrun_hours = fields.Float(
        string='Overrun',
        compute='_compute_time_analysis',
        store=True,
        help='How far actual work has exceeded the estimate: '
             'max(actual_work_hours - estimated_time, 0). Zero while '
             'the task is within estimate.',
    )

    @api.depends('estimated_time', 'actual_work_hours')
    def _compute_time_analysis(self):
        for task in self:
            task.variance_to_finish = task.estimated_time - task.actual_work_hours
            task.remaining_estimated_hours = max(
                task.estimated_time - task.actual_work_hours, 0.0
            )
            task.overrun_hours = max(
                task.actual_work_hours - task.estimated_time, 0.0
            )

    # -- Optional breakdown counters (Part 5, item 13) -------------------

    total_work_session_count = fields.Integer(
        string='Work Session Count',
        compute='_compute_work_session_breakdown_counts',
        store=True,
        help='Total number of work sessions ever recorded for this '
             'task, in any state.',
    )
    total_employees_worked = fields.Integer(
        string='Employees Worked',
        compute='_compute_work_session_breakdown_counts',
        store=True,
        help='Number of distinct employees with at least one running, '
             'paused, completed or transferred session on this task '
             '(cancelled sessions are not counted).',
    )

    @api.depends('work_session_ids.employee_id', 'work_session_ids.state')
    def _compute_work_session_breakdown_counts(self):
        counted_states = ('running', 'paused', 'completed', 'transferred')
        for task in self:
            task.total_work_session_count = len(task.work_session_ids)
            employees = task.work_session_ids.filtered(
                lambda s: s.state in counted_states
            ).mapped('employee_id')
            task.total_employees_worked = len(employees)

    # -- Live display of actual time while a session is running ---------
    #
    # actual_work_hours (above) is STORED and only reflects closed
    # sessions - it is the authoritative, audit-safe number and does
    # not change every second. The fields below are NON-STORED,
    # recomputed on every read, and exist purely so the form can show
    # a live-ish total while someone is actively working. They are
    # never used as the source for variance_to_finish, remaining_
    # estimated_hours or overrun_hours, so those stay stable and
    # meaningful even while a session is running.

    actual_work_hours_live = fields.Float(
        string='Actual Time (Live)',
        compute='_compute_actual_work_hours_live',
        help='actual_work_hours plus the elapsed time of any '
             'currently running session(s) on this task, calculated '
             'at the moment the form is opened/refreshed. This is a '
             'display-only estimate, not stored, and is not used in '
             'Variance/Remaining/Overrun - those remain based on '
             'closed sessions only so they do not drift while someone '
             'is mid-session.',
    )
    live_session_note = fields.Char(
        string='Live Session Note',
        compute='_compute_actual_work_hours_live',
        help='Short note shown next to Actual Time when one or more '
             'employees currently have this task running.',
    )

    @api.depends('actual_work_hours', 'work_session_ids.state',
                 'work_session_ids.start_datetime')
    def _compute_actual_work_hours_live(self):
        now = fields.Datetime.now()
        for task in self:
            running_sessions = task.work_session_ids.filtered(
                lambda s: s.state == 'running'
            )
            elapsed = 0.0
            for session in running_sessions:
                if session.start_datetime:
                    delta = now - session.start_datetime
                    elapsed += max(delta.total_seconds() / 3600.0, 0.0)
            task.actual_work_hours_live = task.actual_work_hours + elapsed
            if running_sessions:
                task.live_session_note = _(
                    'Includes %(count)d employee(s) currently working - '
                    'live total, recalculated on refresh.'
                ) % {'count': len(running_sessions)}
            else:
                task.live_session_note = False

    # ------------------------------------------------------------------
    # PART 4: Start / Pause / Resume for the logged-in employee
    # ------------------------------------------------------------------

    # -- Current-employee helpers -------------------------------------

    def _get_current_employee(self):
        """Safely resolve the hr.employee linked to the logged-in user.

        Deliberately does NOT assume employee_id == user_id, and does
        not rely on a possibly version-specific convenience field on
        res.users - it looks up hr.employee by its own user_id field,
        which is the stable, documented link between the two models.
        Returns an empty recordset if there is no match.
        """
        user = self.env.user
        domain = [('user_id', '=', user.id)]
        company_ids = user.company_ids.ids or [user.company_id.id]
        domain.append(('company_id', 'in', company_ids))
        return self.env['hr.employee'].search(domain, limit=1)

    def _get_current_employee_or_raise(self):
        employee = self._get_current_employee()
        if not employee:
            raise UserError(_('No employee is linked to your Odoo user.'))
        return employee

    def _is_authorized_project_manager_for_task(self):
        """PART 8: single, shared authorization check - used by Start's
        assignment-bypass, Approve/Reject, and Transfer, so all four
        stay consistent instead of drifting.

        Design (per Part 8, item 6 - "do not make every Project
        Manager globally capable of managing every project"): this
        TIGHTENS the behaviour from Parts 6/7, where any member of the
        stock project.group_project_manager group was treated as
        authorized for every task. Part 8 explicitly asks for
        project-scoped authorization instead, so from this part
        onward:

          - base.group_system (Administrator) is still a full,
            global bypass.
          - Otherwise, authorization requires being THIS task's
            project's own manager - either Odoo's standard
            project.user_id (kept in sync with our employee-based
            project_manager_id, see project_project.py) or a member of
            project_manager_ids (the additional-managers list).
          - Being a member of project.group_project_manager alone, for
            some OTHER project, is no longer sufficient by itself.

        project.group_project_manager still matters as the ACL/base
        access gate (see the module's "Project Task Service Manager"
        security group, which implies it) - this method is the
        finer-grained, per-record layer on top of that gate, not a
        replacement for it.
        """
        self.ensure_one()
        return self._is_user_authorized_manager_for_project(self.project_id)

    @api.model
    def _is_user_authorized_manager_for_project(self, project):
        """Same check as _is_authorized_project_manager_for_task(),
        factored out to take a project.project record directly rather
        than reading self.project_id. Needed because create() must
        validate protected billing/estimate fields BEFORE a task
        record (and therefore self.project_id) exists yet.
        """
        user = self.env.user
        if user.has_group('base.group_system'):
            return True
        if not project:
            return False
        if project.user_id and project.user_id.id == user.id:
            return True
        if project.project_manager_ids:
            if user.id in project.project_manager_ids.mapped('user_id').ids:
                return True
        return False

    def _current_user_can_bypass_assignment_check(self):
        """Managers/administrators are allowed to start work on a task
        even if they are not themselves listed as an assignee. Normal
        employees must be assigned. See
        _is_authorized_project_manager_for_task() for the Part 8
        project-scoping rationale.
        """
        return self._is_authorized_project_manager_for_task()

    current_employee_id = fields.Many2one(
        comodel_name='hr.employee',
        string='Current Employee',
        compute='_compute_current_employee_id',
        help='The employee linked to the currently logged-in user '
             '(not stored - this reflects whoever is viewing the '
             'task).',
    )
    my_work_session_state = fields.Selection(
        selection=[
            ('none', 'None'),
            ('running', 'Running'),
            ('paused', 'Paused'),
        ],
        string='Current Work Session',
        compute='_compute_my_work_session_state',
        help='Whether the currently logged-in employee has a running '
             'or paused work session on this specific task. Drives '
             'the Start/Pause/Resume button visibility.',
    )

    @api.depends_context('uid')
    def _compute_current_employee_id(self):
        employee = self._get_current_employee()
        for task in self:
            task.current_employee_id = employee

    @api.depends('work_session_ids.state', 'work_session_ids.employee_id')
    @api.depends_context('uid')
    def _compute_my_work_session_state(self):
        employee = self._get_current_employee()
        for task in self:
            state = 'none'
            if employee:
                sessions = task.work_session_ids.filtered(
                    lambda s: s.employee_id == employee
                )
                if sessions.filtered(lambda s: s.state == 'running'):
                    state = 'running'
                elif sessions.filtered(lambda s: s.state == 'paused'):
                    state = 'paused'
            task.my_work_session_state = state

    # -- Stage helper ---------------------------------------------------

    def _find_in_progress_stage(self):
        """Locate an existing 'In Progress' stage usable by this task's
        project, without assuming a fixed database ID and without
        creating a new stage. Matches case-insensitively since stage
        names are user-editable/translatable.

        Returns an empty recordset if no matching stage is found -
        callers must treat that as "leave the stage alone", per the
        Part 4 requirement not to invent stages.
        """
        self.ensure_one()
        Stage = self.env['project.task.type']
        domain = [('name', '=ilike', 'in progress')]
        if self.project_id:
            domain = ['&', ('name', '=ilike', 'in progress'), '|',
                       ('project_ids', 'in', self.project_id.ids),
                       ('project_ids', '=', False)]
        return Stage.search(domain, limit=1)

    def _move_to_in_progress_stage_if_possible(self):
        self.ensure_one()
        stage = self._find_in_progress_stage()
        if stage and self.stage_id.id != stage.id:
            self.write({'stage_id': stage.id})
        # If no matching stage exists in this project's stage set, the
        # task stage is intentionally left untouched rather than
        # guessing or auto-creating a stage.

    def _check_verification_state_allows_work_or_raise(self):
        """PART 6 gate re-used by Start/Pause/Resume: once a task is
        waiting for manager verification or already approved, no
        further work-session activity is allowed until a manager acts
        (Approve/Reject) or, for a rejected/in-progress task, normally.
        """
        self.ensure_one()
        if self.verification_status == 'waiting':
            raise UserError(_(
                'This task is waiting for manager verification. You '
                'cannot start, pause, or resume work until it has been '
                'reviewed.'
            ))
        if self.verification_status == 'approved':
            raise UserError(_(
                'This task has already been approved and completed. No '
                'further work sessions can be started.'
            ))

    # -- Actions ----------------------------------------------------

    def _lock_for_update(self):
        """PART 11, item 37 (concurrency review): row-level lock on
        this task, via SELECT ... FOR UPDATE, to serialize concurrent
        clicks of the SAME state-changing action on the SAME task -
        the same technique action_start_work/action_resume_work
        already use on the employee row (Part 4), extended here to
        Done/Approve/Reject/Transfer after this review found they had
        no equivalent protection.

        Concretely, without this: two near-simultaneous Done clicks
        could both read verification_status='in_progress' before
        either commits, both pass validation, and both create a
        project.task.verification record - a genuine duplicate-history
        bug, not a hypothetical one. The second concurrent request now
        blocks here until the first transaction commits, then re-reads
        the now-current state and correctly finds the task already
        'waiting' (or already 'approved', etc).
        """
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM project_task WHERE id = %s FOR UPDATE', (self.id,))

    def action_start_work(self):
        """Start a new work session for the logged-in employee on this
        task. See Part 4 spec: validates employee link, task
        assignment, and the one-running-session-per-employee rule
        before creating the session. PART 6 adds the verification-state
        gate and advances verification_status to in_progress on first
        Start.
        """
        self.ensure_one()
        self._check_verification_state_allows_work_or_raise()
        employee = self._get_current_employee_or_raise()

        if not self._current_user_can_bypass_assignment_check():
            if not self.user_ids or employee.user_id not in self.user_ids:
                raise UserError(_('You are no longer assigned to this task.'))

        WorkSession = self.env['project.task.work.session']

        # Serialize concurrent Start clicks/tabs for the same employee:
        # lock the employee's row so a second simultaneous request
        # blocks here until the first transaction commits, then re-reads
        # the now-up-to-date running-session state instead of racing
        # against it. This is the standard Odoo pattern for this kind
        # of "at most one" check and avoids a fragile SQL constraint.
        self.env.cr.execute(
            'SELECT id FROM hr_employee WHERE id = %s FOR UPDATE',
            (employee.id,),
        )
        existing_running = WorkSession.search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'running'),
        ], limit=1)
        if existing_running:
            raise UserError(_(
                'You already have an active work session on another '
                'task. Pause or stop that task before starting another '
                'task.'
            ))

        WorkSession.create({
            'task_id': self.id,
            'employee_id': employee.id,
            'user_id': self.env.user.id,
            'start_datetime': fields.Datetime.now(),
            'state': 'running',
        })
        self._move_to_in_progress_stage_if_possible()
        if self.verification_status == 'not_started':
            self.verification_status = 'in_progress'
        return True

    def action_pause_work(self):
        """Close the logged-in employee's running session on this task."""
        self.ensure_one()
        self._check_verification_state_allows_work_or_raise()
        employee = self._get_current_employee_or_raise()

        session = self.env['project.task.work.session'].search([
            ('task_id', '=', self.id),
            ('employee_id', '=', employee.id),
            ('state', '=', 'running'),
        ], limit=1)
        if not session:
            raise UserError(_(
                'There is no active work session for this task.'
            ))

        now = fields.Datetime.now()
        session.write({
            'end_datetime': now,
            'state': 'paused',
            'closed_by': self.env.user.id,
            'closed_on': now,
        })
        return True

    def action_resume_work(self):
        """Open a brand-new work session for the logged-in employee on
        this task, based on a previously paused session. The paused
        session itself is never modified.
        """
        self.ensure_one()
        self._check_verification_state_allows_work_or_raise()
        employee = self._get_current_employee_or_raise()

        WorkSession = self.env['project.task.work.session']

        # Same concurrency guard as Start, since Resume also opens a
        # new running session and must respect the one-per-employee
        # rule.
        self.env.cr.execute(
            'SELECT id FROM hr_employee WHERE id = %s FOR UPDATE',
            (employee.id,),
        )
        existing_running = WorkSession.search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'running'),
        ], limit=1)
        if existing_running:
            raise UserError(_(
                'You already have an active work session on another '
                'task. Pause or stop that task before starting another '
                'task.'
            ))

        paused_session = WorkSession.search([
            ('task_id', '=', self.id),
            ('employee_id', '=', employee.id),
            ('state', '=', 'paused'),
        ], limit=1, order='end_datetime desc, id desc')
        if not paused_session:
            raise UserError(_(
                'There is no paused work session for this task.'
            ))

        WorkSession.create({
            'task_id': self.id,
            'employee_id': employee.id,
            'user_id': self.env.user.id,
            'start_datetime': fields.Datetime.now(),
            'state': 'running',
        })
        self._move_to_in_progress_stage_if_possible()
        return True

    # ------------------------------------------------------------------
    # PART 6: Submit for verification / Approve / Reject
    # ------------------------------------------------------------------
    #
    # Field-reuse note: the Part 6 spec asks for verification_state,
    # submitted_at, verified_at. Part 2 already created
    # verification_status, submitted_on and verified_on for the exact
    # same purpose. Per this project's own repeated "do not create
    # duplicate fields" rule, Part 6 REUSES those Part 2 fields rather
    # than adding near-identical ones - see the accompanying
    # explanation for the one selection-value rename this required
    # (pending_verification -> waiting).

    can_submit_for_verification = fields.Boolean(
        compute='_compute_can_submit_for_verification',
        help='Whether the logged-in employee is currently allowed to '
             'click Done on this task. Server-side actions re-validate '
             'this independently - this field only drives UI button '
             'visibility.',
    )
    can_verify = fields.Boolean(
        compute='_compute_can_verify',
        help='Whether the logged-in user is currently allowed to '
             'Approve/Reject this task. Server-side actions re-validate '
             'this independently - this field only drives UI button '
             'visibility.',
    )

    @api.depends('verification_status', 'user_ids')
    @api.depends_context('uid')
    def _compute_can_submit_for_verification(self):
        employee = self._get_current_employee()
        can_bypass = self._current_user_can_bypass_assignment_check()
        for task in self:
            allowed = False
            if employee and task.verification_status not in ('waiting', 'approved'):
                is_assigned = bool(task.user_ids) and employee.user_id in task.user_ids
                if can_bypass or is_assigned:
                    allowed = True
            task.can_submit_for_verification = allowed

    @api.depends('verification_status', 'submitted_by', 'project_id.user_id',
                 'project_id.project_manager_ids')
    @api.depends_context('uid')
    def _compute_can_verify(self):
        user = self.env.user
        for task in self:
            is_authorized = task._is_authorized_project_manager_for_task()
            is_self_submission = bool(
                task.submitted_by and task.submitted_by.id == user.id
            )
            task.can_verify = (
                task.verification_status == 'waiting'
                and is_authorized
                and not is_self_submission
            )

    def _check_can_verify_or_raise(self):
        """Server-side re-validation of everything can_verify checks in
        the UI - never trust button visibility alone. Raises UserError
        with a specific reason if the current user may not approve or
        reject this task.

        Permission logic: see _is_authorized_project_manager_for_task()
        - Administrator, OR this task's project's own manager
        (project_id.user_id, kept in sync with the employee-based
        project_manager_id) OR a member of project_manager_ids. As of
        Part 8, generic project.group_project_manager membership for
        an unrelated project is no longer sufficient by itself (see
        that method's docstring for why this changed from Part 6).
        Regardless of role, the user who submitted the task can never
        approve/reject their own submission.
        """
        self.ensure_one()
        user = self.env.user
        if not self._is_authorized_project_manager_for_task():
            raise UserError(_(
                'Only this project\'s authorized Project Manager or an '
                'Administrator may approve or reject this task.'
            ))
        if self.submitted_by and self.submitted_by.id == user.id:
            raise UserError(_(
                'You cannot approve or reject a task that you submitted '
                'yourself.'
            ))
        if self.verification_status != 'waiting':
            raise UserError(_(
                'This task is not currently waiting for verification.'
            ))

    def _find_done_stage(self):
        """Locate an existing 'Done'/'Completed' stage for this task's
        project, without assuming a fixed ID and without creating one.
        Same pattern and same limitation as _find_in_progress_stage()
        in Part 4.
        """
        self.ensure_one()
        Stage = self.env['project.task.type']
        name_domain = ['|', ('name', '=ilike', 'done'), ('name', '=ilike', 'completed')]
        if self.project_id:
            domain = ['&'] + name_domain + ['|',
                       ('project_ids', 'in', self.project_id.ids),
                       ('project_ids', '=', False)]
        else:
            domain = name_domain
        return Stage.search(domain, limit=1)

    # -- PART 6/8: employees must not be able to edit the figures that
    # are supposed to be manager-controlled or system-calculated. ------
    _PROTECTED_MANAGER_ONLY_FIELDS = {
        'estimated_time', 'hourly_rate', 'task_fixed_price', 'is_billable',
    }

    def write(self, vals):
        if self._PROTECTED_MANAGER_ONLY_FIELDS.intersection(vals.keys()):
            for task in self:
                if not task._is_authorized_project_manager_for_task():
                    raise UserError(_(
                        'Only this project\'s authorized Project Manager '
                        'or an Administrator can change Estimated Time, '
                        'Hourly Rate, Task Price, or the Billable flag.'
                    ))
        # PART 10, item 5: capture previous assignees before the write
        # so we can tell who is genuinely NEW afterwards. Skipped
        # entirely when skip_assignment_notification is set in
        # context - used by _transfer_task(), which sends its own
        # dedicated transfer notification instead of the generic
        # "New task assigned" one (see _notify_task_transferred).
        track_assignees = (
            'user_ids' in vals
            and not self.env.context.get('skip_assignment_notification')
        )
        previous_assignee_ids = {}
        if track_assignees:
            previous_assignee_ids = {task.id: set(task.user_ids.ids) for task in self}
        res = super().write(vals)
        if track_assignees:
            for task in self:
                newly_added_ids = set(task.user_ids.ids) - previous_assignee_ids.get(task.id, set())
                if newly_added_ids:
                    task._notify_new_assignees(self.env['res.users'].browse(newly_added_ids))
        return res

    @api.model_create_multi
    def create(self, vals_list):
        tasks = self._create_with_billing_guard(vals_list)
        # PART 10, item 5: notify assignees set at creation time too -
        # not just ones added via a later write() (see the write()
        # override above). Every user in a freshly-created task's
        # user_ids is "newly added" by definition, so no de-duplication
        # against a "previous" state is needed here the way write()
        # needs it.
        for task in tasks:
            if task.user_ids:
                task._notify_new_assignees(task.user_ids)
        return tasks

    def _create_with_billing_guard(self, vals_list):
        """Renamed from the old create() body (Part 8) so the new
        create() above can wrap it with Part 10's assignment
        notification without duplicating the billing-guard logic.
        """
        protected_field_defaults = {
            'estimated_time': 0.0,
            'hourly_rate': 0.0,
            'task_fixed_price': 0.0,
            'is_billable': True,
        }
        for vals in vals_list:
            changed_protected = {
                field for field in self._PROTECTED_MANAGER_ONLY_FIELDS
                if field in vals and vals[field] != protected_field_defaults.get(field)
            }
            if changed_protected:
                project = self.env['project.project'].browse(vals.get('project_id')) \
                    if vals.get('project_id') else self.env['project.project']
                if not self._is_user_authorized_manager_for_project(project):
                    raise UserError(_(
                        'Only this project\'s authorized Project Manager '
                        'or an Administrator can set Estimated Time, '
                        'Hourly Rate, Task Price, or the Billable flag '
                        'to a non-default value.'
                    ))
        return super().create(vals_list)

    def action_submit_for_verification(self):
        """The employee-facing 'Done' button. Named
        action_submit_for_verification (not action_done) to avoid any
        collision with existing Odoo task behaviour tied to that name.
        """
        self.ensure_one()
        self._lock_for_update()
        employee = self._get_current_employee_or_raise()

        if not self._current_user_can_bypass_assignment_check():
            if not self.user_ids or employee.user_id not in self.user_ids:
                raise UserError(_('You are no longer assigned to this task.'))

        if self.verification_status in ('waiting', 'approved'):
            raise UserError(_(
                'This task cannot be submitted again right now (current '
                'status: %s).'
            ) % dict(self._fields['verification_status'].selection).get(
                self.verification_status
            ))

        running_session = self.env['project.task.work.session'].search([
            ('task_id', '=', self.id),
            ('employee_id', '=', employee.id),
            ('state', '=', 'running'),
        ], limit=1)
        if running_session:
            raise UserError(_(
                'You must pause or stop your active work session before '
                'submitting the task for verification.'
            ))

        has_worked = self.env['project.task.work.session'].search_count([
            ('task_id', '=', self.id),
            ('employee_id', '=', employee.id),
            ('state', 'in', ('paused', 'completed', 'transferred')),
        ]) > 0
        if not has_worked:
            raise UserError(_(
                'No completed work session was found for you on this '
                'task yet. Start and pause work before submitting for '
                'verification.'
            ))

        if not (self.employee_remarks and self.employee_remarks.strip()):
            raise UserError(_(
                'Please enter your remarks before submitting the task '
                'for verification.'
            ))

        # PART 10, item 13/19: DONE must not silently send the task
        # nowhere. Resolved via the same project-manager configuration
        # used for Approve/Reject authorization (Part 8) - never a
        # hard-coded fallback user.
        manager_user = self._get_project_manager_user()
        if not manager_user:
            raise UserError(_(
                'No project manager is configured for this project. '
                'Please contact the administrator.'
            ))

        now = fields.Datetime.now()
        self.write({
            'verification_status': 'waiting',
            'submitted_by': self.env.user.id,
            'submitted_on': now,
        })
        self.env['project.task.verification'].create({
            'task_id': self.id,
            'employee_id': employee.id,
            'submitted_by': self.env.user.id,
            'submitted_at': now,
            'employee_remarks': self.employee_remarks,
            'result': 'waiting',
        })
        self._schedule_service_notification(
            manager_user,
            summary=_('Task waiting for verification: %s') % self.name,
            note=_(
                'Employee: %(employee)s\n'
                'Estimated Time: %(estimated).2fh\n'
                'Actual Time: %(actual).2fh\n'
                'Variance: %(variance).2fh\n'
                'Employee Remarks: %(remarks)s'
            ) % {
                'employee': employee.name,
                'estimated': self.estimated_time,
                'actual': self.actual_work_hours,
                'variance': self.variance_to_finish,
                'remarks': self.employee_remarks,
            },
        )
        return True

    def action_approve_task(self):
        self.ensure_one()
        self._lock_for_update()
        self._check_can_verify_or_raise()

        now = fields.Datetime.now()
        self.write({
            'verification_status': 'approved',
            'verified_by': self.env.user.id,
            'verified_on': now,
        })

        history = self.env['project.task.verification'].search([
            ('task_id', '=', self.id),
            ('result', '=', 'waiting'),
        ], order='submitted_at desc, id desc', limit=1)
        if history:
            history.write({
                'verified_by': self.env.user.id,
                'verified_at': now,
                'manager_remarks': self.manager_remarks or False,
                'result': 'approved',
            })

        # Stage handling: same policy as Part 4's In Progress move - if
        # no matching Done/Completed stage exists for this project, the
        # approval still succeeds (verification_status is the
        # authoritative business result) but the Odoo stage is left
        # untouched rather than guessed at, and a chatter note records
        # why, so the gap is visible rather than silently swallowed.
        stage = self._find_done_stage()
        if stage:
            if self.stage_id.id != stage.id:
                self.write({'stage_id': stage.id})
        else:
            self.message_post(body=_(
                'Task approved, but no "Done"/"Completed" stage was '
                'found for this project, so the task stage was left '
                'unchanged. Configure such a stage if you want approved '
                'tasks to move automatically.'
            ))

        self._complete_open_verification_activities(
            feedback=_('Approved.'),
        )
        if history and history.submitted_by:
            self._schedule_service_notification(
                history.submitted_by,
                summary=_('Task approved: %s') % self.name,
            )
        return True

    def action_reject_task(self):
        self.ensure_one()
        self._lock_for_update()
        self._check_can_verify_or_raise()

        if not (self.manager_remarks and self.manager_remarks.strip()):
            raise UserError(_(
                'Please provide a reason for rejecting this task.'
            ))

        now = fields.Datetime.now()
        history = self.env['project.task.verification'].search([
            ('task_id', '=', self.id),
            ('result', '=', 'waiting'),
        ], order='submitted_at desc, id desc', limit=1)
        if history:
            history.write({
                'verified_by': self.env.user.id,
                'verified_at': now,
                'manager_remarks': self.manager_remarks,
                'result': 'rejected',
            })

        # Simplified workflow (per spec's own "keep it simple" option):
        # the task goes straight back to in_progress so the employee
        # can resume immediately, rather than parking at a visible
        # "rejected" status that would need a further "send back to
        # work" click. The permanent record that this cycle was
        # rejected still lives in verification_history_ids
        # (result='rejected') - nothing is lost, it's just not also
        # frozen on the task's live status field.
        self.write({
            'verification_status': 'in_progress',
            'verified_by': self.env.user.id,
            'verified_on': now,
        })

        self._complete_open_verification_activities(
            feedback=_('Rejected: %s') % self.manager_remarks,
        )
        submitted_by = history.submitted_by if history else self.submitted_by
        if submitted_by:
            self._schedule_service_notification(
                submitted_by,
                summary=_('Task requires correction: %s') % self.name,
                note=self.manager_remarks,
            )
        return True

    # ------------------------------------------------------------------
    # PART 10: Notifications, built on Odoo's own mail.activity
    # infrastructure (project.task already inherits mail.thread /
    # mail.activity.mixin via core Project - no new mixin, no external
    # email system). One shared activity type (see
    # data/mail_activity_type_data.xml) is reused for every
    # notification kind; each is distinguished by its summary text and
    # targeted user, exactly the "concise, business-language, no
    # duplicate activity types" approach the spec asks for.
    # ------------------------------------------------------------------

    @api.model
    def _get_service_notification_activity_type(self):
        return self.env.ref(
            'project_task_service_management.mail_activity_type_service_task_notification',
            raise_if_not_found=False,
        )

    def _get_project_manager_user(self):
        """The single user notifications about this task's verification
        should go to: this task's project's primary manager
        (project_id.user_id, kept in sync with project_manager_id -
        Part 8) if set, otherwise the first configured additional
        manager (project_manager_ids). Returns an empty recordset if
        neither is configured - callers decide what to do with that
        (action_submit_for_verification blocks submission entirely per
        item 13/19; nothing hard-codes a fallback user).
        """
        self.ensure_one()
        project = self.project_id
        if not project:
            return self.env['res.users']
        if project.user_id:
            return project.user_id
        if project.project_manager_ids:
            first_manager = project.project_manager_ids[0]
            if first_manager.user_id:
                return first_manager.user_id
        return self.env['res.users']

    def _schedule_service_notification(self, user, summary, note=None):
        """Schedule one activity for `user` on this task, unless `user`
        is empty or is the person who just triggered the action (no
        point notifying someone about their own click). Silently does
        nothing if the custom activity type is missing for any reason,
        rather than blocking the underlying business action - a failed
        notification must never be allowed to block Start/Done/Approve/
        Reject/Transfer, which have already fully completed by the time
        this is called.
        """
        self.ensure_one()
        if not user or user.id == self.env.user.id:
            return
        activity_type = self._get_service_notification_activity_type()
        if not activity_type:
            # PART 11, item 52: this should never happen in a normal
            # install (the type is a data file shipped with the
            # module), so if it's missing that's worth a log line for
            # whoever administers the server - but still must not
            # raise, per this method's own docstring.
            _logger.warning(
                'Service Task Management: could not send notification '
                '"%s" on task id %s - the '
                '"Service Task Notification" activity type is missing.',
                summary, self.id,
            )
            return
        self.activity_schedule(
            activity_type_id=activity_type.id,
            user_id=user.id,
            summary=summary,
            note=note or False,
        )

    def _complete_open_verification_activities(self, feedback=None):
        """When a manager Approves or Rejects, mark their own open
        'waiting for verification' activity on this task as done
        (item 12: avoid a stale activity claiming the task is still
        awaiting action after the manager has already acted). Scoped
        to activities of our own type assigned to the CURRENT user
        (the manager doing the approving/rejecting) - never touches
        another user's activities.
        """
        self.ensure_one()
        activity_type = self._get_service_notification_activity_type()
        if not activity_type:
            return
        open_activities = self.activity_ids.filtered(
            lambda a: a.activity_type_id.id == activity_type.id
            and a.user_id.id == self.env.user.id
        )
        if open_activities:
            open_activities.action_feedback(feedback=feedback or False)

    def _notify_new_assignees(self, users):
        """PART 10, item 5: notify newly-added assignees. Only ever
        called for users genuinely newly added in this write() call
        (see write() below) - never re-fires for assignees who were
        already on the task, so it cannot create duplicate activities
        just from the task being saved again (item 15).
        """
        self.ensure_one()
        for user in users:
            self._schedule_service_notification(
                user,
                summary=_('New task assigned: %s') % self.name,
                note=_('Project: %(project)s\nCustomer: %(customer)s') % {
                    'project': self.project_id.name or '-',
                    'customer': self.partner_id.name or '-',
                },
            )

    def _notify_task_transferred(self, from_employee, to_employee, reason):
        """PART 10, items 6-7. Reason is optional throughout this
        module (Part 8 correction) - the notification text adapts
        cleanly to either case rather than treating a blank reason as
        an error or oddity.
        """
        self.ensure_one()
        if reason and reason.strip():
            to_note = _('Task transferred to you. Reason: %s') % reason.strip()
        else:
            to_note = _('Task transferred to you.')
        self._schedule_service_notification(
            to_employee.user_id,
            summary=_('Task transferred to you: %s') % self.name,
            note=to_note,
        )
        # Previous employee: deliberately no billing/rate information -
        # just enough to explain the task left their list (item 7).
        self._schedule_service_notification(
            from_employee.user_id,
            summary=_('Task transferred: %s is now assigned to another '
                       'employee.') % self.name,
        )

    # ------------------------------------------------------------------
    # PART 7: Manager-initiated task transfer
    # ------------------------------------------------------------------
    # The task record itself is never duplicated or recreated - transfer
    # only ever: (a) closes the outgoing employee's running session as
    # 'transferred', (b) swaps the assignee on the existing task, and
    # (c) writes one project.task.transfer audit row. Everything else on
    # the task (Task Code, customer, project, estimated time, all past
    # Work Sessions, verification history) is completely untouched.

    transfer_history_ids = fields.One2many(
        comodel_name='project.task.transfer',
        inverse_name='task_id',
        string='Transfer History',
        readonly=True,
        help='Every manager-initiated transfer this task has ever gone '
             'through, oldest last. Never edited or deleted - a task '
             'transferred A to B to C keeps both transfer records.',
    )
    can_transfer_task = fields.Boolean(
        compute='_compute_can_transfer_task',
        help='Whether the logged-in user is currently allowed to see '
             'the Transfer Task button. Server-side re-validated '
             'independently in _check_can_transfer_or_raise() - this '
             'field only drives UI visibility.',
    )
    employee_time_breakdown = fields.Text(
        string='Time by Employee',
        compute='_compute_employee_time_breakdown',
        help='Actual time worked per employee on this task, one line '
             'each, computed from Work Sessions (Completed/Paused/'
             'Transferred only, same rule as Actual Time itself). A '
             'simple readonly summary - the full detail remains '
             'available per-session in the Work Sessions list, and '
             'across tasks via the standalone Work Sessions menu\'s '
             '"Group By: Employee" filter (Part 3).',
    )

    @api.depends('verification_status', 'project_id.user_id',
                 'project_id.project_manager_ids')
    @api.depends_context('uid')
    def _compute_can_transfer_task(self):
        for task in self:
            is_authorized = task._is_authorized_project_manager_for_task()
            task.can_transfer_task = (
                is_authorized
                and task.verification_status not in ('waiting', 'approved')
            )

    @api.depends('work_session_ids.duration', 'work_session_ids.state',
                 'work_session_ids.employee_id')
    def _compute_employee_time_breakdown(self):
        counted_states = ('completed', 'paused', 'transferred')
        for task in self:
            totals = {}
            for session in task.work_session_ids:
                if session.state in counted_states and session.employee_id:
                    totals[session.employee_id] = totals.get(
                        session.employee_id, 0.0
                    ) + session.duration
            lines = []
            for employee, hours in totals.items():
                whole_hours = int(hours)
                minutes = int(round((hours - whole_hours) * 60))
                if minutes == 60:
                    whole_hours += 1
                    minutes = 0
                lines.append('%s: %d:%02d' % (employee.name, whole_hours, minutes))
            task.employee_time_breakdown = '\n'.join(lines) if lines else False

    def _check_can_transfer_or_raise(self):
        """Server-side re-validation of everything can_transfer_task
        checks in the UI, plus the state checks that don't depend on
        who is asking. Same permission logic as verification (Part 6/
        8): see _is_authorized_project_manager_for_task().
        """
        self.ensure_one()
        if not self._is_authorized_project_manager_for_task():
            raise UserError(_(
                'Only this project\'s authorized Project Manager or an '
                'Administrator may transfer this task.'
            ))
        if self.verification_status == 'approved':
            raise UserError(_('An approved task cannot be transferred.'))
        if self.verification_status == 'waiting':
            raise UserError(_(
                'This task is waiting for manager verification and '
                'cannot be transferred yet. Reject it (returning it to '
                'work) first if the work needs to go to a different '
                'employee.'
            ))

    def action_transfer_task(self):
        """Header button: validates permission/state, then opens the
        transfer wizard for the manager to pick from/to employee and a
        reason. No task data changes until the wizard's own Transfer
        button (action_transfer) is clicked.
        """
        self.ensure_one()
        self._check_can_transfer_or_raise()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfer Task'),
            'res_model': 'project.task.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_task_id': self.id},
        }

    def _transfer_task(self, from_employee, to_employee, reason):
        """Core transfer logic, called only by the wizard
        (project.task.transfer.wizard.action_transfer). Kept as a
        method on the task itself - rather than living entirely inside
        the wizard - so it can be unit-tested or reused without going
        through the UI, and so all the invariants it protects live next
        to the model they protect.

        Re-validates permission/state (never trusts that the wizard's
        own guards were the only path here), then:
          1. Closes from_employee's running session on this task, if
             any, as 'transferred' (never 'completed' - the work was
             interrupted, not finished).
          2. Swaps from_employee's user off the task's assignees and
             adds to_employee's user on, leaving every OTHER assignee
             (e.g. other employees still concurrently working)
             completely untouched.
          3. Writes one permanent project.task.transfer audit record.

        Never touches: Task Code, customer, project, estimated_time,
        any other employee's sessions, verification_status/history,
        employee_remarks, manager_remarks.
        """
        self.ensure_one()
        self._lock_for_update()
        self._check_can_transfer_or_raise()

        if not from_employee:
            raise UserError(_(
                'Please select the employee the task is being '
                'transferred from.'
            ))
        if not to_employee:
            raise UserError(_(
                'Please select the employee to transfer the task to.'
            ))
        if from_employee.id == to_employee.id:
            raise UserError(_(
                'Transfer employee and receiving employee must be '
                'different.'
            ))
        if not from_employee.user_id or from_employee.user_id not in self.user_ids:
            raise UserError(_(
                'The selected employee is not currently assigned to '
                'this task.'
            ))
        if not to_employee.user_id:
            raise UserError(_(
                'The selected employee does not have a linked Odoo '
                'user and cannot receive this task.'
            ))

        now = fields.Datetime.now()

        # Close ONLY the outgoing employee's own running session, if
        # any. Any other employee's running session (e.g. someone else
        # concurrently working the same task) is a completely separate
        # record and is never touched by this search/write.
        running_session = self.env['project.task.work.session'].search([
            ('task_id', '=', self.id),
            ('employee_id', '=', from_employee.id),
            ('state', '=', 'running'),
        ], limit=1)
        if running_session:
            running_session.write({
                'end_datetime': now,
                'state': 'transferred',
                'closed_by': self.env.user.id,
                'closed_on': now,
                'transfer_reason': reason,
            })
        # Design choice: a PAUSED session belonging to from_employee is
        # deliberately left as 'paused', not relabelled 'transferred'.
        # It already represents a closed, accurately-durationed piece
        # of work that ended (via Pause) before the transfer decision -
        # relabelling it would misrepresent *why* it closed. Only a
        # session that was actually still running at the moment of
        # transfer is transfer-interrupted, so only that one gets
        # state='transferred'.

        # Reassign: remove from_employee's user, add to_employee's
        # user, leave every other current assignee untouched.
        # skip_assignment_notification: this transfer sends its own
        # dedicated notification below (item 6/7) instead of the
        # generic "New task assigned" one from write() (item 5) -
        # without this flag the incoming employee would get both.
        updated_user_ids = (self.user_ids - from_employee.user_id) | to_employee.user_id
        self.with_context(skip_assignment_notification=True).write({
            'user_ids': [(6, 0, updated_user_ids.ids)],
        })

        self.env['project.task.transfer'].create({
            'task_id': self.id,
            'from_employee_id': from_employee.id,
            'to_employee_id': to_employee.id,
            'transferred_by': self.env.user.id,
            'transferred_at': now,
            'reason': reason,
        })
        self._notify_task_transferred(from_employee, to_employee, reason)
        return True
