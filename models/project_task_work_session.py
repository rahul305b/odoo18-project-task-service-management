from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProjectTaskWorkSession(models.Model):
    """A single, immutable-once-closed period of work performed by one
    employee on one task.

    PART 3 SCOPE:
    - This is the data model and its validation rules only.
    - No Start/Pause/Resume/Transfer/Submit actions exist yet — records
      are created manually (e.g. by a manager) for now, exactly as the
      test procedure describes.
    - The "one running session per employee" business rule is NOT
      enforced here as a hard constraint; see the note on
      `_check_single_running_session_note` below for why, and what
      Part 4 needs to finalize.
    """
    _name = 'project.task.work.session'
    _description = 'Project Task Work Session'
    _order = 'start_datetime desc, id desc'

    # ------------------------------------------------------------------
    # Core relations
    # ------------------------------------------------------------------
    task_id = fields.Many2one(
        comodel_name='project.task',
        string='Task',
        required=True,
        ondelete='cascade',
        index=True,
        help='Task this work session belongs to.',
    )
    project_id = fields.Many2one(
        comodel_name='project.project',
        string='Project',
        related='task_id.project_id',
        store=True,
        index=True,
        readonly=True,
        help='Project of the related task, kept in sync automatically. '
             'Stored so it can be used for search filters and Group By '
             '(a dotted path like task_id.project_id cannot be used '
             'directly in a search view group_by context).',
    )
    employee_id = fields.Many2one(
        comodel_name='hr.employee',
        string='Employee',
        required=True,
        index=True,
        # PART 11 hardening: explicit rather than relying on Odoo's
        # implicit default for a required Many2one. 'restrict' means
        # an employee record cannot be deleted while historical work
        # sessions reference them - this is the correct, safe
        # behaviour for audit data (never silently lose or orphan a
        # Work Session because HR later removes an employee record;
        # in practice employees are archived/deactivated, not
        # hard-deleted, which this does not affect at all).
        ondelete='restrict',
        help='Employee who performed this session of work.',
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Customer',
        related='task_id.partner_id',
        store=True,
        index=True,
        readonly=True,
        help="Customer of the related task, kept in sync automatically. "
             "Stored for the same reason as project_id above - dotted "
             "paths cannot be used directly in search-view group_by "
             "contexts (PART 9: needed for the dashboard's Customer "
             "filter/Group By on Work Session reporting).",
    )
    user_id = fields.Many2one(
        comodel_name='res.users',
        string='User',
        required=True,
        ondelete='restrict',
        help='Odoo user account corresponding to the employee who '
             'performed the work. Derived automatically from the '
             "employee's linked user when a session is created via "
             'Start/Resume.',
    )

    # ------------------------------------------------------------------
    # Timing
    # ------------------------------------------------------------------
    start_datetime = fields.Datetime(
        string='Start',
        required=True,
        help='Actual beginning of this work session.',
    )
    end_datetime = fields.Datetime(
        string='End',
        readonly=True,
        help='Actual end of this work session — set when the session is '
             'paused, the task is transferred, or the work is '
             'completed/cancelled. Left empty while the session is '
             'still running.',
    )
    duration = fields.Float(
        string='Duration (hours)',
        compute='_compute_duration',
        store=True,
        readonly=True,
        help='Length of this session in hours. Calculated from '
             'start/end datetime once the session is closed. For a '
             'still-running session this is a snapshot computed at the '
             'last recomputation, not a live-updating timer.',
    )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    state = fields.Selection(
        selection=[
            ('running', 'Running'),
            ('completed', 'Completed'),
            ('paused', 'Paused'),
            ('transferred', 'Transferred'),
            ('cancelled', 'Cancelled'),
        ],
        string='State',
        default='running',
        required=True,
        help='Current state of this work session. In Part 3 this is set '
             'manually; automatic transitions via Start/Pause/Resume/'
             'Transfer/Submit actions will be added in a later part.',
    )

    # ------------------------------------------------------------------
    # Free-text explanations
    # ------------------------------------------------------------------
    pause_reason = fields.Text(
        string='Pause Reason',
        help='Optional explanation entered when this session was '
             'paused.',
    )
    transfer_reason = fields.Text(
        string='Transfer Reason',
        help='Reason the session was closed due to the task being '
             'transferred to another employee.',
    )

    # ------------------------------------------------------------------
    # Closing audit trail (distinct from create_uid/create_date, which
    # Odoo already tracks for record creation)
    # ------------------------------------------------------------------
    closed_by = fields.Many2one(
        comodel_name='res.users',
        string='Closed By',
        readonly=True,
        help='User who closed this session (paused it, transferred the '
             'task, or submitted/completed the work).',
    )
    closed_on = fields.Datetime(
        string='Closed On',
        readonly=True,
        help='Date/time this session was closed.',
    )

    _sql_constraints = [
        (
            'duration_non_negative',
            'CHECK(duration >= 0)',
            'Work session duration must not be negative.',
        ),
    ]

    # ------------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------------
    @api.depends('start_datetime', 'end_datetime', 'state')
    def _compute_duration(self):
        now = fields.Datetime.now()
        for session in self:
            if session.start_datetime and session.end_datetime:
                delta = session.end_datetime - session.start_datetime
                hours = delta.total_seconds() / 3600.0
            elif session.start_datetime and session.state == 'running':
                # Snapshot only - recomputed when a dependency changes,
                # not a live timer. A real live display will be added
                # with the Start/Pause UI in a later part.
                delta = now - session.start_datetime
                hours = delta.total_seconds() / 3600.0
            else:
                hours = 0.0
            session.duration = max(hours, 0.0)

    # ------------------------------------------------------------------
    # PART 9: live elapsed time for the "Currently Working" dashboard
    # section. Deliberately NOT stored, unlike `duration` above -
    # `duration` only updates when start/end/state actually change
    # (so a running session's stored duration goes stale between
    # pauses), which is fine for the audit-safe historical figure but
    # wrong for "how long has this been running right now". This field
    # recomputes fresh every time it's read (e.g. on dashboard load/
    # refresh) directly from the authoritative start_datetime, with no
    # separate stored value that could drift or need a background job
    # to keep current.
    # ------------------------------------------------------------------
    elapsed_hours = fields.Float(
        string='Elapsed (running)',
        compute='_compute_elapsed_hours',
        help='For a currently running session, hours elapsed since '
             'start_datetime as of the moment this was last loaded/'
             'refreshed - not a continuously ticking value. 0 for any '
             'non-running session. Purely a display convenience; '
             'start_datetime remains the single source of truth.',
    )

    @api.depends('start_datetime', 'state')
    def _compute_elapsed_hours(self):
        now = fields.Datetime.now()
        for session in self:
            if session.state == 'running' and session.start_datetime:
                delta = now - session.start_datetime
                session.elapsed_hours = max(delta.total_seconds() / 3600.0, 0.0)
            else:
                session.elapsed_hours = 0.0

    # ------------------------------------------------------------------
    # PART 9: dashboard/reporting actions. Read-only reporting on top
    # of the existing model - no state, validation, or business logic
    # from Parts 3/4/7 is touched.
    # ------------------------------------------------------------------
    @api.model
    def _get_dashboard_domain_for_current_user(self):
        """Same project-specific scoping principle as
        project.task._is_authorized_project_manager_for_task() (Part
        8): Administrators see everything; anyone else sees only work
        sessions on tasks under a project they are the manager (or an
        additional manager) of. Expressed as a plain ORM domain
        (rather than a per-record Python/ir.rule check) specifically
        so it stays a single indexed, efficient query - see Part 9
        item 31 (performance) and item 29 (project-specific security).
        """
        if self.env.user.has_group('base.group_system'):
            return []
        uid = self.env.user.id
        return [
            '|',
            ('task_id.project_id.user_id', '=', uid),
            ('task_id.project_id.project_manager_ids.user_id', '=', uid),
        ]

    @api.model
    def action_open_work_session_report(self):
        """Menu: Service Task Dashboard > Work Session Report."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Work Session Report'),
            'res_model': 'project.task.work.session',
            'view_mode': 'list,pivot,graph,form',
            'views': [
                (self.env.ref('project_task_service_management.view_project_task_work_session_list').id, 'list'),
                (self.env.ref('project_task_service_management.view_project_task_work_session_pivot').id, 'pivot'),
                (self.env.ref('project_task_service_management.view_project_task_work_session_graph').id, 'graph'),
                (False, 'form'),
            ],
            'search_view_id': [self.env.ref('project_task_service_management.view_project_task_work_session_search').id, 'search'],
            'domain': self._get_dashboard_domain_for_current_user(),
            'context': {'search_default_groupby_employee': 1},
        }

    @api.model
    def action_open_currently_working(self):
        """Menu: Service Task Dashboard > Currently Working. Fixed
        domain (state=running) ANDed with the same project scoping.
        """
        domain = self._get_dashboard_domain_for_current_user() + [('state', '=', 'running')]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Currently Working'),
            'res_model': 'project.task.work.session',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('project_task_service_management.view_project_task_work_session_currently_working_list').id, 'list'),
                (False, 'form'),
            ],
            'search_view_id': [self.env.ref('project_task_service_management.view_project_task_work_session_search').id, 'search'],
            'domain': domain,
            'context': {},
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @api.constrains('start_datetime', 'end_datetime')
    def _check_start_before_end(self):
        for session in self:
            if session.start_datetime and session.end_datetime:
                if session.start_datetime > session.end_datetime:
                    raise ValidationError(
                        'The start time of a work session cannot be '
                        'after its end time (Task: %s, Employee: %s).'
                        % (session.task_id.name, session.employee_id.name)
                    )

    @api.constrains('state', 'end_datetime')
    def _check_end_datetime_required_for_closed_states(self):
        closed_states = ('completed', 'paused', 'transferred', 'cancelled')
        for session in self:
            if session.state in closed_states and not session.end_datetime:
                raise ValidationError(
                    'A work session in state "%s" must have an end '
                    'date/time (Task: %s, Employee: %s).'
                    % (
                        dict(session._fields['state'].selection).get(session.state),
                        session.task_id.name,
                        session.employee_id.name,
                    )
                )

    def write(self, vals):
        """Guard rails for Part 3:

        - A session can never be moved back to 'running' once it has
          been closed (completed/paused/transferred/cancelled). This
          protects historical data even though no UI action performs
          state transitions yet - manual edits (e.g. via the list view)
          are covered too.
        - Once a session is closed, its core factual fields
          (who/what/when) become immutable for everyone except
          Administrators, so historical sessions used for billing and
          reporting cannot be silently altered. Administrators retain
          the ability to correct genuine data-entry mistakes.
        """
        is_admin = self.env.user.has_group('base.group_system')

        if not is_admin:
            protected_fields = {
                'task_id', 'employee_id', 'user_id',
                'start_datetime', 'end_datetime', 'duration',
            }
            closed_states = ('completed', 'paused', 'transferred', 'cancelled')
            if protected_fields.intersection(vals.keys()):
                for session in self:
                    if session.state in closed_states:
                        raise ValidationError(
                            'This work session is closed (%s) and its '
                            'recorded time/employee/task cannot be '
                            'changed. Contact an administrator if this '
                            'needs correcting.'
                            % dict(session._fields['state'].selection).get(session.state)
                        )

            if vals.get('state') == 'running':
                for session in self:
                    if session.state == 'completed':
                        raise ValidationError(
                            'A completed work session cannot be changed '
                            'back to Running.'
                        )

        return super().write(vals)

    def unlink(self):
        """Historical, closed sessions cannot be deleted by non-admins.
        This backs up the access-rights restriction with a model-level
        guard in case unlink is ever reachable via a group that
        shouldn't have it.
        """
        is_admin = self.env.user.has_group('base.group_system')
        if not is_admin:
            closed_states = ('completed', 'paused', 'transferred', 'cancelled')
            for session in self:
                if session.state in closed_states:
                    raise ValidationError(
                        'Closed work sessions are historical records and '
                        'cannot be deleted. Contact an administrator if '
                        'this needs correcting.'
                    )
        return super().unlink()

    # ------------------------------------------------------------------
    # NOTE on the "one running session per employee" rule
    # ------------------------------------------------------------------
    # The business rule ("an employee should normally have only ONE
    # running work session at a time") is intentionally NOT enforced
    # here as a hard constraint yet:
    #
    # - A Python @api.constrains check race-conditions against
    #   concurrent writes (two near-simultaneous Start clicks could
    #   both pass validation before either commits).
    # - A naive SQL unique index on (employee_id) filtered by
    #   state='running' is technically possible in PostgreSQL via a
    #   partial unique index, but wiring that up correctly alongside
    #   Odoo's ORM save cycle, and deciding the right user-facing error
    #   handling, belongs with the Start/Resume action logic itself -
    #   not the bare data model.
    #
    # Part 4 (Start/Pause/Resume/Transfer implementation) will add a
    # proper safeguard at the point where sessions are actually opened,
    # using either a `SELECT ... FOR UPDATE`-style guarded search or a
    # partial unique SQL index, decided once the exact concurrency
    # requirements of that action are clear.
