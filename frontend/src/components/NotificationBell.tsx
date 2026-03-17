import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useNotifications, useUnreadCount, useMarkNotificationsRead, useMarkAllRead } from '@/hooks/useNotifications';
import type { Notification } from '@/types';

function BellIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  );
}

function timeAgo(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

function NotificationItem({
  notification,
  onRead,
}: {
  notification: Notification;
  onRead: (id: string) => void;
}) {
  const navigate = useNavigate();

  const handleClick = () => {
    if (!notification.read) {
      onRead(notification.id);
    }
    if (notification.job_id) {
      navigate(`/jobs?highlight=${notification.job_id}`);
    }
  };

  return (
    <DropdownMenuItem
      className="flex flex-col items-start gap-0.5 py-2 px-3 cursor-pointer"
      onClick={handleClick}
    >
      <div className="flex items-center gap-2 w-full">
        {!notification.read && (
          <span className="h-2 w-2 rounded-full bg-blue-500 shrink-0" />
        )}
        <span className={`text-sm truncate max-w-[250px] ${notification.type === 'starred_company_job' ? 'font-semibold' : 'font-medium'}`}>
          {notification.type === 'starred_company_job' ? '⭐ ' : ''}{notification.title}
        </span>
        <span className="text-[10px] text-muted-foreground ml-auto shrink-0">
          {timeAgo(notification.created_at)}
        </span>
      </div>
      {notification.body && (
        <span className="text-xs text-muted-foreground truncate max-w-[280px] pl-4">
          {notification.body}
        </span>
      )}
    </DropdownMenuItem>
  );
}

export function NotificationBell() {
  const { data: countData } = useUnreadCount();
  const { data: notifications } = useNotifications();
  const markRead = useMarkNotificationsRead();
  const markAllRead = useMarkAllRead();

  const unreadCount = countData?.count ?? 0;
  const items = notifications ?? [];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="relative flex h-8 w-8 items-center justify-center rounded-full outline-none hover:bg-muted transition-colors">
        <BellIcon className="h-5 w-5" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80 max-h-[400px] overflow-y-auto">
        <div className="flex items-center justify-between px-3 py-2">
          <span className="text-sm font-semibold">Notifications</span>
          {unreadCount > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 text-xs"
              onClick={() => markAllRead.mutate()}
            >
              Mark all read
            </Button>
          )}
        </div>
        <DropdownMenuSeparator />
        {items.length === 0 ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            No notifications yet
          </div>
        ) : (
          items.slice(0, 20).map((n) => (
            <NotificationItem
              key={n.id}
              notification={n}
              onRead={(id) => markRead.mutate([id])}
            />
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
