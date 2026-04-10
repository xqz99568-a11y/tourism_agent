import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

type BudgetChartProps = {
  budgetLines: string[];
};

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884D8', '#82CA9D'];

function parseBudgetData(lines: string[]) {
  const data: { name: string; value: number }[] = [];
  
  lines.forEach(line => {
    const match = line.match(/[-•]\s*(.+?)[：:]\s*¥?(\d+)/);
    if (match) {
      const name = match[1].trim();
      const value = parseInt(match[2], 10);
      if (name && value > 0) {
        data.push({ name, value });
      }
    }
  });
  
  return data;
}

export function BudgetChart({ budgetLines }: BudgetChartProps) {
  const data = parseBudgetData(budgetLines);
  
  if (data.length === 0) {
    return null;
  }
  
  const total = data.reduce((sum, item) => sum + item.value, 0);
  
  return (
    <Card className="border-border/70 bg-slate-50/80 dark:bg-slate-900/70">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold tracking-wide text-slate-900 dark:text-slate-50">
          预算分布
        </CardTitle>
        <p className="text-xs text-muted-foreground">总预算: ¥{total.toLocaleString()}</p>
      </CardHeader>
      <CardContent>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) => `${name} ${((percent || 0) * 100).toFixed(0)}%`}
                outerRadius={80}
                fill="#8884d8"
                dataKey="value"
              >
                {data.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip 
                formatter={(value) => `¥${Number(value).toLocaleString()}`}
                contentStyle={{ 
                  backgroundColor: 'rgba(255, 255, 255, 0.95)',
                  border: '1px solid #e2e8f0',
                  borderRadius: '8px',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
                }}
              />
              <Legend 
                verticalAlign="bottom" 
                height={36}
                formatter={(value) => <span className="text-xs text-slate-700 dark:text-slate-300">{value}</span>}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
