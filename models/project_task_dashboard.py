from odoo import _, api, models


class ProjectTask(models.Model):
    """PART 9: Manager Dashboard actions. Deliberately kept in its own
    file, separate from project_task.py, since these are pure
    reporting entry points - they compute a scoped domain and hand
    off to standard Odoo list/pivot/graph views, and touch none of the
    business logic (Start/Pause/Resume/Done/Approve/Reject/Transfer/
    billing) that already lives in project_task.py.

    Every KPI/figure shown by these actions reuses fields already
    computed and stored in earlier parts (estimated_time,
    actual_work_hours, variance_to_finish, remaining_estimated_hours,
    overrun_hours, billable_amount, verification_status) - nothing is
    recalculated here.
    """
    _inherit = 'project.task'

    @api.model
    def _get_dashboard_domain_for_current_user(self):
        """Project-specific scoping (Part 8/9): Administrators see
        every task; anyone else sees only tasks under a project they
        are the manager (or an additional manager) of. A plain,
        indexed ORM domain - not a per-record Python check or an
        ir.rule - for the performance and OR-combination reasons
        explained in Part 8's security notes.
        """
        if self.env.user.has_group('base.group_system'):
            return []
        uid = self.env.user.id
        return [
            '|',
            ('project_id.user_id', '=', uid),
            ('project_id.project_manager_ids.user_id', '=', uid),
        ]

    def _dashboard_view_list(self):
        """Shared views list (list/pivot/graph/form) for every task-
        based dashboard action below, all pointing at the same three
        purpose-built PART 9 views plus the standard task form (so
        'open the actual task' uses the real, full task form, per item
        23 - never a duplicated dashboard-only form)."""
        return [
            (self.env.ref('project_task_service_management.view_task_performance_list').id, 'list'),
            (self.env.ref('project_task_service_management.view_task_performance_pivot').id, 'pivot'),
            (self.env.ref('project_task_service_management.view_task_performance_graph').id, 'graph'),
            (False, 'form'),
        ]

    @api.model
    def action_open_task_performance(self):
        """Menu: Service Task Dashboard > Task Performance. This is
        also where the KPI summary lives: open the Pivot tab with no
        row/column grouping and it shows one line of totals across
        Estimated/Actual/Variance/Billable Amount for whatever the
        current filters/domain select - the native Odoo equivalent of
        a KPI card row, with no extra code to maintain. Group by
        Customer or Project from the search panel to get the item
        15/16 Customer/Project summaries from the exact same view.
        """
        return {
            'type': 'ir.actions.act_window',
            'name': _('Task Performance'),
            'res_model': 'project.task',
            'view_mode': 'list,pivot,graph,form',
            'views': self._dashboard_view_list(),
            'search_view_id': [self.env.ref('project_task_service_management.view_task_performance_search').id, 'search'],
            'domain': self._get_dashboard_domain_for_current_user(),
            'context': {},
        }

    @api.model
    def action_open_pending_verification(self):
        """Menu: Service Task Dashboard > Pending Verification."""
        domain = self._get_dashboard_domain_for_current_user() + [
            ('verification_status', '=', 'waiting'),
        ]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pending Manager Verification'),
            'res_model': 'project.task',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('project_task_service_management.view_task_pending_verification_list').id, 'list'),
                (False, 'form'),
            ],
            'search_view_id': [self.env.ref('project_task_service_management.view_task_performance_search').id, 'search'],
            'domain': domain,
            'context': {},
        }

    @api.model
    def action_open_overrun_tasks(self):
        """Menu: Service Task Dashboard > Tasks Over Estimate. Sorted
        largest overrun first, per item 11.
        """
        domain = self._get_dashboard_domain_for_current_user() + [
            ('overrun_hours', '>', 0),
        ]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tasks Over Estimate'),
            'res_model': 'project.task',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('project_task_service_management.view_task_overrun_list').id, 'list'),
                (False, 'form'),
            ],
            'search_view_id': [self.env.ref('project_task_service_management.view_task_performance_search').id, 'search'],
            'domain': domain,
            'context': {},
        }

    @api.model
    def action_open_billing_summary(self):
        """Menu: Service Task Dashboard > Billing Summary. Same
        Task Performance data, opened with billing-relevant columns
        emphasized by default and grouped by Customer, since billing
        is inherently a per-customer question (item 17). Reporting
        only - no invoices, no accounting entries.
        """
        return {
            'type': 'ir.actions.act_window',
            'name': _('Billing Summary'),
            'res_model': 'project.task',
            'view_mode': 'list,pivot,form',
            'views': [
                (self.env.ref('project_task_service_management.view_task_billing_summary_list').id, 'list'),
                (self.env.ref('project_task_service_management.view_task_performance_pivot').id, 'pivot'),
                (False, 'form'),
            ],
            'search_view_id': [self.env.ref('project_task_service_management.view_task_performance_search').id, 'search'],
            'domain': self._get_dashboard_domain_for_current_user(),
            'context': {'search_default_groupby_customer': 1},
        }
