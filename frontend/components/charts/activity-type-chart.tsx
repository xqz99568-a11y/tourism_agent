import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

type ActivityTypeChartProps = {
  days: Array<{ title: string; lines: string[] }>;
};

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884D8', '#82CA9D', '#FFC0CB', '#00CED1'];

const ACTIVITY_TYPES: Record<string, string[]> = {
  '自然风光': ['西湖', '山', '湖', '公园', '湿地', '海滩', '森林', '瀑布'],
  '历史古迹': ['寺', '庙', '宫', '府', '古镇', '古城', '遗址', '博物馆', '纪念馆'],
  '美食体验': ['美食', '小吃', '餐厅', '夜市', '美食街', '老街'],
  '购物娱乐': ['购物', '商场', '步行街', '商圈'],
  '夜景观赏': ['夜景', '灯光', '夜游', '江景'],
  '亲子活动': ['动物园', '海洋馆', '科技馆', '乐园', '主题公园'],
  '文化艺术': ['艺术', '展览', '剧院', '演出'],
  '休闲放松': ['温泉', 'SPA', '度假', '休闲']
};

function parseActivityTypes(days: Array<{ title: string; lines: string[] }>) {
  const typeCount: Record<string, number> = {};
  
  days.forEach(day => {
    day.lines.forEach(line => {
      const text = line.toLowerCase();
      let matched = false;
      
      for (const [type, keywords] of Object.entries(ACTIVITY_TYPES)) {
        if (keywords.some(keyword => text.includes(keyword.toLowerCase()))) {
          typeCount[type] = (typeCount[type] || 0) + 1;
          matched = true;
          break;
        }
      }
      
      if (!matched && line.includes(':')) {
        typeCount['其他活动'] = (typeCount['其他活动'] || 0) + 1;
      }
    });
  });
  
  return Object.entries(typeCount)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
}

export function ActivityTypeChart({ days }: ActivityTypeChartProps) {
  const data = parseActivityTypes(days);
  
  if (data.length === 0) {
    return null;
  }
  
  const total = data.reduce((sum, item) => sum + item.value, 0);
  
  return (
    <Card className="border-border/70 bg-slate-50/80 dark:bg-slate-900/70">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold tracking-wide text-slate-900 dark:text-slate-50">
          活动类型分布
        </CardTitle>
        <p className="text-xs text-muted-foreground">共 {total} 项活动</p>
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
                label={({ name, percent }) => (percent || 0) > 0.05 ? `${name} ${((percent || 0) * 100).toFixed(0)}%` : ''}
                outerRadius={80}
                fill="#8884d8"
                dataKey="value"
              >
                {data.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip 
                formatter={(value) => `${value} 项`}
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
