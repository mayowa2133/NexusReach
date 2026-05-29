import { Link } from 'react-router-dom';
import { Download, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useDeleteAccount, useExportAccountData } from '@/hooks/useSettings';
import { useAuthStore } from '@/stores/auth';

export function AccountDataPanel() {
  const exportAccountData = useExportAccountData();
  const deleteAccount = useDeleteAccount();
  const signOut = useAuthStore((state) => state.signOut);

  const handleExport = async () => {
    try {
      await exportAccountData.mutateAsync();
      toast.success('Account export started');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to export account data');
    }
  };

  const handleDelete = async () => {
    try {
      await deleteAccount.mutateAsync();
      toast.success('Account deleted');
      await signOut().catch(() => {});
      window.location.assign('/login');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete account');
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Account Data</CardTitle>
        <CardDescription>
          Export your data or permanently delete your NexusReach account.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-1">
            <div className="font-medium">Export account data</div>
            <p className="text-sm text-muted-foreground">
              Download profile, jobs, contacts, messages, outreach, LinkedIn
              graph rows, settings, and activity records as JSON. OAuth refresh
              tokens and stored API keys are redacted.
            </p>
          </div>
          <Button
            variant="outline"
            onClick={handleExport}
            disabled={exportAccountData.isPending}
            className="sm:w-40"
          >
            <Download className="mr-2 h-4 w-4" />
            {exportAccountData.isPending ? 'Exporting...' : 'Export'}
          </Button>
        </div>

        <div className="flex flex-col gap-3 rounded-lg border border-destructive/30 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-1">
            <div className="font-medium">Delete account</div>
            <p className="text-sm text-muted-foreground">
              Permanently remove your auth identity and app-owned NexusReach
              data, including encrypted email tokens and imported LinkedIn graph
              rows.
            </p>
          </div>
          <AlertDialog>
            <AlertDialogTrigger
              render={
                <Button
                  variant="destructive"
                  disabled={deleteAccount.isPending}
                  className="sm:w-40"
                />
              }
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete your account?</AlertDialogTitle>
                <AlertDialogDescription>
                  This permanently deletes your NexusReach account data. This
                  cannot be undone.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  variant="destructive"
                  onClick={handleDelete}
                  disabled={deleteAccount.isPending}
                >
                  {deleteAccount.isPending ? 'Deleting...' : 'Delete account'}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>

        <p className="text-xs text-muted-foreground">
          See the{' '}
          <Link to="/privacy" className="underline underline-offset-4">
            Privacy Policy
          </Link>{' '}
          and{' '}
          <Link to="/terms" className="underline underline-offset-4">
            Terms
          </Link>
          .
        </p>
      </CardContent>
    </Card>
  );
}
