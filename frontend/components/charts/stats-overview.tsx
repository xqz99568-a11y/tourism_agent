import { Clock, MapPin, DollarSign, Calendar } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

type StatsOverviewProps = {
  days: Array<{ title: string; lines: string[] }>;
  budgetLines: string[];
};

function calculateStats(days: Array<{ title: string; lines: string[] }>, budgetLines: string[]) {
  let totalActivities = 0;
  let totalLocations = new Set<string>();
  let totalBudget = 0;
  
  days.forEach(day => {
    day.lines.forEach(line => {
      if (line.includes(':')) {
        totalActivities++;
        
        const locMatch = line.match(/[:：]\s*(.+?)\s*[\(（]/);
        if (locMatch) {
          totalLocations.add(locMatch[1].trim());
        }
      }
    });
  });
  
  budgetLines.forEach(line => {
    const match = line.match(/¥?(\d+)/);
    if (match) {
      totalBudget += parseInt(match[1], 10);
    }
  });
  
  return {
    totalDays: days.length,
    totalActivities,
    totalLocations: totalLocations.size,
    totalBudget
  };
}

export function StatsOverview({ days, budgetLines }: StatsOverviewProps) {
  const stats = calculateStats(days, budgetLines);
  
  if (stats.totalDays === 0) {
    return null;
  }
  
  const statItems = [
    {
      icon: Calendar,
      label: '行程天数',
      value: `${stats.totalDays} 天`,
      color: 'text-blue-600 dark:text-blue-400',
      bgColor: 'bg-blue-100 dark:bg-blue-950'
    },
    {
      icon: MapPin,
      label: '景点数量',
      value: `${stats.totalLocations} 个`,
      color: 'text-green-600 dark:text-green-400',
      bgColor: 'bg-green-100 dark:bg-green-950'
    },
    {
      icon: Clock,
      label: '活动项目',
      value: `${stats.totalActivities} 项`,
      color: 'text-purple-600 dark:text-purple-400',
      bgColor: 'bg-purple-100 dark:bg-purple-950'
    },
    {
      icon: DollarSign,
      label: '预估预算',
      value: stats.totalBudget > 0 ? `¥${stats.totalBudget.toLocaleString()}` : '待定',
      color: 'text-orange-600 dark:text-orange-400',
      bgColor: 'bg-orange-100 dark:bg-orange-950'
    }
  ];
  
  return (
    <Card className="border-border/70 bg-slate-50/80 dark:bg-slate-900/70">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold tracking-wide text-slate-900 dark:text-slate-50">
          行程概览
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {statItems.map((item, index) => (
            <div 
              key={index}
              className="flex items-center gap-3 p-3 rounded-xl bg-white dark:bg-slate-800 border border-border/50"
            >
              <div className={`p-2 rounded-lg ${item.bgColor}`}>
                <item.icon className={`h-5 w-5 ${item.color}`} />
              </div>
              <div>
                <p className="text-xs text-muted-foreground">{item.label}</p>
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-50">{item.value}</p>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
