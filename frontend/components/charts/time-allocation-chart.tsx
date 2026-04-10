import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

type TimeAllocationChartProps = {
  days: Array<{ title: string; lines: string[] }>;
};

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884D8'];

function parseTimeAllocation(days: Array<{ title: string; lines: string[] }>) {
  const data: { day: string; activities: number; travel: number; rest: number; meals: number }[] = [];
  
  days.forEach((day, index) => {
    let activities = 0;
    let travel = 0;
    let rest = 0;
    let meals = 0;
    
    day.lines.forEach(line => {
      const timeMatch = line.match(/^(\d{1,2}):(\d{2})/);
      if (timeMatch) {
        const hour = parseInt(timeMatch[1], 10);
        
        if (line.includes('早餐') || line.includes('午餐') || line.includes('晚餐') || line.includes('美食')) {
          meals += 1;
        } else if (line.includes('休息') || line.includes('自由活动')) {
          rest += 1;
        } else if (line.includes('前往') || line.includes('到达') || line.includes('返回')) {
          travel += 1;
        } else {
          activities += 1;
        }
      }
    });
    
    if (activities > 0 || travel > 0 || rest > 0 || meals > 0) {
      data.push({
        day: `第${index + 1}天`,
        activities: activities * 1.5,
        travel: travel * 0.5,
        rest: rest * 1,
        meals: meals * 1
      });
    }
  });
  
  return data;
}

export function TimeAllocationChart({ days }: TimeAllocationChartProps) {
  const data = parseTimeAllocation(days);
  
  if (data.length === 0) {
    return null;
  }
  
  return (
    <Card className="border-border/70 bg-slate-50/80 dark:bg-slate-900/70">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold tracking-wide text-slate-900 dark:text-slate-50">
          行程时间分配
        </CardTitle>
        <p className="text-xs text-muted-foreground">每天各类活动时间分布（小时）</p>
      </CardHeader>
      <CardContent>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data}
              margin={{
                top: 20,
                right: 30,
                left: 20,
                bottom: 5,
              }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis 
                dataKey="day" 
                tick={{ fontSize: 12, fill: '#64748b' }}
                axisLine={{ stroke: '#e2e8f0' }}
              />
              <YAxis 
                tick={{ fontSize: 12, fill: '#64748b' }}
                axisLine={{ stroke: '#e2e8f0' }}
                label={{ value: '小时', angle: -90, position: 'insideLeft', style: { fontSize: 12, fill: '#64748b' } }}
              />
              <Tooltip 
                contentStyle={{ 
                  backgroundColor: 'rgba(255, 255, 255, 0.95)',
                  border: '1px solid #e2e8f0',
                  borderRadius: '8px',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
                }}
                formatter={(value) => `${Number(value).toFixed(1)}小时`}
              />
              <Legend 
                verticalAlign="top" 
                height={36}
                formatter={(value) => {
                  const labels: Record<string, string> = {
                    activities: '游览活动',
                    travel: '交通时间',
                    rest: '休息时间',
                    meals: '用餐时间'
                  };
                  return <span className="text-xs text-slate-700 dark:text-slate-300">{labels[value] || value}</span>;
                }}
              />
              <Bar dataKey="activities" stackId="a" fill="#0088FE" name="游览活动" />
              <Bar dataKey="travel" stackId="a" fill="#00C49F" name="交通时间" />
              <Bar dataKey="rest" stackId="a" fill="#FFBB28" name="休息时间" />
              <Bar dataKey="meals" stackId="a" fill="#FF8042" name="用餐时间" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
