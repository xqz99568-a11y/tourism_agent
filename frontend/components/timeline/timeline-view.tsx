import React, { useState, useRef, useEffect } from 'react';
import { Clock, MapPin, Calendar, Camera, Utensils, Hotel, Car, Info, ShoppingBag, Coffee, Mountain, Landmark, Theater, Music, Activity, ChevronDown, Star } from 'lucide-react';

interface TimelineItem {
  time: string;
  title: string;
  location: string;
  description?: string;
  type?: 'attraction' | 'meal' | 'transport' | 'accommodation' | 'shopping' | 'coffee' | 'outdoor' | 'cultural' | 'entertainment' | 'sports' | 'other';
  imageUrl?: string;
  rating?: number;
  duration?: string;
  tags?: string[];
}

interface TimelineDay {
  day: number;
  title: string;
  date?: string;
  items: TimelineItem[];
}

interface TimelineViewProps {
  days: TimelineDay[];
  className?: string;
}

// 根据活动类型获取图标
function getActivityIcon(type: string) {
  switch (type) {
    case 'attraction':
      return <Camera className="h-4 w-4" />;
    case 'meal':
      return <Utensils className="h-4 w-4" />;
    case 'transport':
      return <Car className="h-4 w-4" />;
    case 'accommodation':
      return <Hotel className="h-4 w-4" />;
    case 'shopping':
      return <ShoppingBag className="h-4 w-4" />;
    case 'coffee':
      return <Coffee className="h-4 w-4" />;
    case 'outdoor':
      return <Mountain className="h-4 w-4" />;
    case 'cultural':
      return <Landmark className="h-4 w-4" />;
    case 'entertainment':
      return <Theater className="h-4 w-4" />;
    case 'sports':
      return <Activity className="h-4 w-4" />;
    default:
      return <Info className="h-4 w-4" />;
  }
}

// 根据活动类型获取颜色
function getActivityColor(type: string) {
  switch (type) {
    case 'attraction':
      return 'bg-emerald-500 border-emerald-200 dark:border-emerald-900';
    case 'meal':
      return 'bg-amber-500 border-amber-200 dark:border-amber-900';
    case 'transport':
      return 'bg-blue-500 border-blue-200 dark:border-blue-900';
    case 'accommodation':
      return 'bg-purple-500 border-purple-200 dark:border-purple-900';
    case 'shopping':
      return 'bg-pink-500 border-pink-200 dark:border-pink-900';
    case 'coffee':
      return 'bg-brown-500 border-brown-200 dark:border-brown-900';
    case 'outdoor':
      return 'bg-green-500 border-green-200 dark:border-green-900';
    case 'cultural':
      return 'bg-orange-500 border-orange-200 dark:border-orange-900';
    case 'entertainment':
      return 'bg-purple-400 border-purple-200 dark:border-purple-800';
    case 'sports':
      return 'bg-red-500 border-red-200 dark:border-red-900';
    default:
      return 'bg-sky-500 border-sky-200 dark:border-sky-900';
  }
}

// 根据活动类型获取名称
function getActivityTypeName(type: string) {
  switch (type) {
    case 'attraction':
      return '景点';
    case 'meal':
      return '餐饮';
    case 'transport':
      return '交通';
    case 'accommodation':
      return '住宿';
    case 'shopping':
      return '购物';
    case 'coffee':
      return '咖啡';
    case 'outdoor':
      return '户外';
    case 'cultural':
      return '文化';
    case 'entertainment':
      return '娱乐';
    case 'sports':
      return '运动';
    default:
      return '其他';
  }
}

function TimelineView({ days, className = '' }: TimelineViewProps) {
  const [activeDay, setActiveDay] = useState(0);
  const [activeItem, setActiveItem] = useState<number | null>(null);
  const [expandedItems, setExpandedItems] = useState<number[]>([]);
  const [filterType, setFilterType] = useState<string | null>(null);
  const timelineRef = useRef<HTMLDivElement>(null);

  const activeTimeline = days[activeDay];

  // 滚动到选中的时间点
  useEffect(() => {
    if (activeItem !== null && timelineRef.current) {
      const itemElement = timelineRef.current.children[activeItem] as HTMLElement;
      if (itemElement) {
        itemElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  }, [activeItem]);

  // 为活动添加类型和图片
  const enhancedItems = activeTimeline.items.map((item, index) => {
    // 更详细的类型推断
    let type: 'attraction' | 'meal' | 'transport' | 'accommodation' | 'shopping' | 'coffee' | 'outdoor' | 'cultural' | 'entertainment' | 'sports' | 'other' = 'other';
    const lowerTitle = item.title.toLowerCase();
    const lowerLocation = item.location.toLowerCase();
    
    if (lowerTitle.includes('餐厅') || lowerTitle.includes('吃饭') || lowerTitle.includes('美食') || lowerTitle.includes('餐') || lowerTitle.includes('饭店') || lowerTitle.includes('餐馆')) {
      type = 'meal';
    } else if (lowerTitle.includes('酒店') || lowerTitle.includes('住宿') || lowerTitle.includes('宾馆') || lowerTitle.includes('旅馆') || lowerTitle.includes('民宿')) {
      type = 'accommodation';
    } else if (lowerTitle.includes('交通') || lowerTitle.includes('前往') || lowerTitle.includes('出发') || lowerTitle.includes('到达') || lowerTitle.includes('机场') || lowerTitle.includes('车站')) {
      type = 'transport';
    } else if (lowerTitle.includes('购物') || lowerTitle.includes('商场') || lowerTitle.includes('商店') || lowerTitle.includes('购物街')) {
      type = 'shopping';
    } else if (lowerTitle.includes('咖啡') || lowerTitle.includes('咖啡馆') || lowerTitle.includes('星巴克') || lowerTitle.includes('cafe')) {
      type = 'coffee';
    } else if (lowerTitle.includes('公园') || lowerTitle.includes('山') || lowerTitle.includes('湖') || lowerTitle.includes('海滩') || lowerTitle.includes('户外')) {
      type = 'outdoor';
    } else if (lowerTitle.includes('博物馆') || lowerTitle.includes('文化') || lowerTitle.includes('历史') || lowerTitle.includes('古迹')) {
      type = 'cultural';
    } else if (lowerTitle.includes('剧院') || lowerTitle.includes('电影') || lowerTitle.includes('娱乐') || lowerTitle.includes('演出')) {
      type = 'entertainment';
    } else if (lowerTitle.includes('运动') || lowerTitle.includes('健身') || lowerTitle.includes('体育')) {
      type = 'sports';
    } else {
      type = 'attraction';
    }

    return {
      ...item,
      type,
      imageUrl: `https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=${encodeURIComponent(item.title + ' scenic view')}&image_size=landscape_4_3`,
      rating: 4.0 + Math.random() * 1.0, // 模拟评分
      duration: `${Math.floor(Math.random() * 2) + 1}小时`, // 模拟时长
      tags: [getActivityTypeName(type), ...(Math.random() > 0.5 ? ['推荐'] : [])] // 模拟标签
    };
  });

  // 过滤活动
  const filteredItems = filterType ? enhancedItems.filter(item => item.type === filterType) : enhancedItems;

  // 切换展开/收起状态
  const toggleExpand = (index: number) => {
    setExpandedItems(prev => prev.includes(index) 
      ? prev.filter(i => i !== index) 
      : [...prev, index]
    );
  };

  // 所有活动类型
  const allTypes = ['attraction', 'meal', 'transport', 'accommodation', 'shopping', 'coffee', 'outdoor', 'cultural', 'entertainment', 'sports'];

  return (
    <div className={`rounded-xl md:rounded-2xl border border-border/70 bg-white dark:bg-slate-950 shadow-soft overflow-hidden ${className}`}>
      <div className="p-3 md:p-4 border-b border-border/70">
        <div className="flex items-center justify-between mb-2 md:mb-3">
          <div className="flex items-center gap-2">
            <Calendar className="h-4 w-4 md:h-5 md:w-5 text-sky-600 dark:text-sky-400" />
            <h3 className="text-base md:text-lg font-semibold text-slate-900 dark:text-slate-50">行程时间线</h3>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setFilterType(null)}
              className={`flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium transition-colors ${
                filterType === null
                  ? 'bg-sky-500 text-white shadow-sm'
                  : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-700'
              }`}
            >
              全部
            </button>
          </div>
        </div>
        
        {/* 天数选择 */}
        <div className="flex gap-1 md:gap-2 overflow-x-auto pb-1 md:pb-2 mb-3">
          {days.map((day, index) => (
            <button
              key={day.day}
              onClick={() => {
                setActiveDay(index);
                setActiveItem(null);
                setFilterType(null);
                setExpandedItems([]);
              }}
              className={`px-3 py-1.5 md:px-4 md:py-2 rounded-full text-xs md:text-sm font-medium transition-all whitespace-nowrap ${
                activeDay === index
                  ? 'bg-sky-500 text-white shadow-md'
                  : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-700'
              }`}
            >
              Day {day.day}
            </button>
          ))}
        </div>
        
        {/* 活动类型过滤器 */}
        <div className="flex gap-1 md:gap-2 overflow-x-auto pb-1">
          {allTypes.map((type) => (
            <button
              key={type}
              onClick={() => setFilterType(filterType === type ? null : type)}
              className={`flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium transition-all ${
                filterType === type
                  ? `${getActivityColor(type)} text-white shadow-sm`
                  : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-700'
              }`}
            >
              {getActivityIcon(type)}
              <span className="hidden sm:inline">{getActivityTypeName(type)}</span>
            </button>
          ))}
        </div>
      </div>
      
      {/* 交互式时间轴 */}
      {enhancedItems.length > 0 && (
        <div className="px-3 py-2 md:px-4 md:py-3 border-b border-border/70 bg-slate-50/50 dark:bg-slate-900/50">
          <div className="flex items-center gap-1 md:gap-2 overflow-x-auto pb-1 md:pb-2">
            {filteredItems.map((item, index) => (
              <button
                key={index}
                onClick={() => setActiveItem(index)}
                className={`flex items-center gap-1 flex-shrink-0 px-2 py-1 md:px-3 md:py-1.5 rounded-full text-xs font-medium transition-all ${
                  activeItem === index
                    ? `${getActivityColor(item.type)} text-white shadow-sm`
                    : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-700'
                }`}
              >
                {getActivityIcon(item.type)}
                <span>{item.time}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      
      <div className="p-3 md:p-4">
        <h4 className="text-base md:text-md font-semibold text-slate-900 dark:text-slate-50 mb-3 md:mb-4">
          {activeTimeline.title}
          {activeTimeline.date && (
            <span className="ml-2 text-xs md:text-sm text-slate-500 dark:text-slate-400">{activeTimeline.date}</span>
          )}
        </h4>
        
        {filteredItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-slate-500">
            <Info className="h-8 w-8 mb-2" />
            <p>没有找到匹配的活动</p>
          </div>
        ) : (
          <div className="relative">
            {/* Timeline line */}
            <div className="absolute left-3 md:left-4 top-0 bottom-0 w-0.5 bg-sky-200 dark:bg-slate-700"></div>
            
            {/* Timeline items */}
            <div ref={timelineRef} className="space-y-3 md:space-y-4 lg:space-y-6">
              {filteredItems.map((item, index) => (
                <div 
                  key={index} 
                  className={`relative pl-7 md:pl-8 lg:pl-10 transition-all duration-300 ${
                    activeItem === index ? 'scale-105' : ''
                  }`}
                >
                  {/* Timeline dot */}
                  <div className={`absolute left-1.5 md:left-2 top-1.5 w-3 h-3 rounded-full border-2 border-white dark:border-slate-950 ${getActivityColor(item.type)}`}>
                    <div className="absolute inset-0.5 rounded-full bg-white dark:bg-slate-950"></div>
                  </div>
                  
                  {/* Timeline content */}
                  <div className={`rounded-xl border ${getActivityColor(item.type).replace('bg-', 'border-')} bg-slate-50 dark:bg-slate-900 p-2 md:p-3 lg:p-4 hover:shadow-md transition-all`}>
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <div className="flex items-center gap-2">
                        <div className={`p-1.5 rounded-lg ${getActivityColor(item.type).replace('bg-', 'bg-').replace('border-', 'text-')}`}>
                          <div className="h-3 w-3">
                            {getActivityIcon(item.type)}
                          </div>
                        </div>
                        <div className="flex-1">
                          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1">
                            <div className="flex items-center gap-1 text-xs font-medium text-slate-900 dark:text-slate-50">
                              <Clock className="h-3 w-3 text-sky-500" />
                              <span>{item.time}</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <div className="flex items-center gap-1 text-xs text-slate-600 dark:text-slate-300">
                                <MapPin className="h-3 w-3 text-sky-500" />
                                <span className="truncate max-w-[100px] md:max-w-[150px] lg:max-w-none">{item.location}</span>
                              </div>
                              {item.rating && (
                                <div className="flex items-center gap-1 text-xs">
                                  <Star className="h-3 w-3 text-amber-500 fill-amber-500" />
                                  <span className="text-slate-600 dark:text-slate-300">{item.rating.toFixed(1)}</span>
                                </div>
                              )}
                            </div>
                          </div>
                          <div className="flex items-center gap-2 mt-1 flex-wrap">
                            <h5 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
                              {item.title}
                            </h5>
                            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${getActivityColor(item.type).replace('bg-', 'bg-').replace('border-', 'text-')}`}>
                              {getActivityTypeName(item.type)}
                            </span>
                          </div>
                        </div>
                      </div>
                      <button
                        onClick={() => toggleExpand(index)}
                        className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 flex-shrink-0"
                      >
                        <ChevronDown className={`h-4 w-4 transition-transform ${expandedItems.includes(index) ? 'rotate-180' : ''}`} />
                      </button>
                    </div>
                    
                    {/* 活动图片 */}
                    {item.imageUrl && (
                      <div className="mb-2 rounded-lg overflow-hidden">
                        <img 
                          src={item.imageUrl} 
                          alt={item.title} 
                          className="w-full h-20 md:h-24 lg:h-32 object-cover"
                        />
                      </div>
                    )}
                    
                    {/* 基本信息 */}
                    <div className="flex flex-wrap gap-2 mb-2">
                      {item.duration && (
                        <div className="flex items-center gap-1 text-xs text-slate-600 dark:text-slate-300">
                          <Clock className="h-3 w-3" />
                          <span>时长：{item.duration}</span>
                        </div>
                      )}
                      {item.tags && item.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {item.tags.map((tag, tagIndex) => (
                            <span key={tagIndex} className="px-2 py-0.5 rounded-full text-xs bg-sky-100 text-sky-700 dark:bg-sky-950/30 dark:text-sky-300">
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    
                    {/* 展开信息 */}
                    {expandedItems.includes(index) && (
                      <div className="mt-2 pt-2 border-t border-slate-200 dark:border-slate-700">
                        {/* 活动描述 */}
                        {item.description ? (
                          <p className="text-xs md:text-sm text-slate-600 dark:text-slate-300">
                            {item.description}
                          </p>
                        ) : (
                          <p className="text-xs md:text-sm text-slate-500 dark:text-slate-400">
                            暂无详细描述
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                  
                  {/* Connector line */}
                  {index < filteredItems.length - 1 && (
                    <div className="absolute left-3 top-5 bottom-0 w-0.5 bg-sky-200 dark:bg-slate-700 h-3 md:h-4 lg:h-6"></div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export { TimelineView };