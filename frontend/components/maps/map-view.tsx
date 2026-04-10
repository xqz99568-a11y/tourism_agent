import React, { useEffect, useMemo, useState } from 'react';
import { MapPin, Clock, Map, Navigation, Camera, Info, ArrowRight, Star, Clock3, ChevronDown } from 'lucide-react';

// 导入Leaflet CSS
import 'leaflet/dist/leaflet.css';

// 动态导入Leaflet，避免SSR问题
const MapContainer = React.lazy(() => import('react-leaflet').then(module => ({ default: module.MapContainer })));
const TileLayer = React.lazy(() => import('react-leaflet').then(module => ({ default: module.TileLayer })));
const Marker = React.lazy(() => import('react-leaflet').then(module => ({ default: module.Marker })));
const Popup = React.lazy(() => import('react-leaflet').then(module => ({ default: module.Popup })));
const Polyline = React.lazy(() => import('react-leaflet').then(module => ({ default: module.Polyline })));
const Tooltip = React.lazy(() => import('react-leaflet').then(module => ({ default: module.Tooltip })));

interface Location {
  name: string;
  lat: number;
  lng: number;
  description?: string;
  time?: string;
  imageUrl?: string;
  rating?: number;
  duration?: string;
  tags?: string[];
  address?: string;
}

interface ItineraryDay {
  day: number;
  title: string;
  locations: Location[];
}

interface MapViewProps {
  itinerary: ItineraryDay[];
  className?: string;
}

// 模拟地点图片数据
const locationImages: Record<string, string> = {
  '西湖': 'https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=West%20Lake%20in%20Hangzhou%20with%20traditional%20Chinese%20bridge%20and%20pagoda%2C%20scenic%20view&image_size=landscape_16_9',
  '灵隐寺': 'https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=Lingyin%20Temple%20in%20Hangzhou%2C%20traditional%20Buddhist%20temple%20with%20ancient%20architecture&image_size=landscape_16_9',
  '雷峰塔': 'https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=Leifeng%20Pagoda%20in%20Hangzhou%2C%20traditional%20Chinese%20pagoda%20with%20sunset%20view&image_size=landscape_16_9',
  '千岛湖': 'https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=Thousand%20Islands%20Lake%20in%20Zhejiang%2C%20scenic%20lake%20with%20many%20islands&image_size=landscape_16_9',
  '黄山': 'https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=Huangshan%20Mountain%20with%20sunrise%20and%20sea%20of%20clouds%2C%20scenic%20Chinese%20mountain&image_size=landscape_16_9',
  '故宫': 'https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=Forbidden%20City%20in%20Beijing%2C%20ancient%20Chinese%20imperial%20palace%20with%20red%20walls&image_size=landscape_16_9',
  '长城': 'https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=Great%20Wall%20of%20China%20winding%20through%20mountains%2C%20scenic%20view&image_size=landscape_16_9',
  '颐和园': 'https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=Summer%20Palace%20in%20Beijing%2C%20traditional%20Chinese%20garden%20with%20lake%20and%20pavilions&image_size=landscape_16_9',
  '天安门': 'https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=Tiananmen%20Square%20in%20Beijing%2C%20historic%20gateway%20with%20Chinese%20flag&image_size=landscape_16_9'
};

// 模拟地点标签数据
const locationTags: Record<string, string[]> = {
  '西湖': ['自然景观', '文化遗产', '拍照胜地'],
  '灵隐寺': ['佛教文化', '历史古迹', '宁静场所'],
  '雷峰塔': ['历史古迹', '观景台', '文化遗产'],
  '千岛湖': ['自然景观', '水上活动', '度假胜地'],
  '黄山': ['自然景观', '登山', '摄影天堂'],
  '故宫': ['历史古迹', '文化遗产', '博物馆'],
  '长城': ['历史古迹', '文化遗产', '登山'],
  '颐和园': ['历史古迹', '园林', '文化遗产'],
  '天安门': ['历史古迹', '政治地标', '文化遗产']
};

function MapView({ itinerary, className = '' }: MapViewProps) {
  const allLocations = useMemo(() => {
    return itinerary.flatMap(day => day.locations);
  }, [itinerary]);

  const center = useMemo(() => {
    if (allLocations.length === 0) {
      return [39.9042, 116.4074] as [number, number]; // Default to Beijing
    }
    const latSum = allLocations.reduce((sum, loc) => sum + loc.lat, 0);
    const lngSum = allLocations.reduce((sum, loc) => sum + loc.lng, 0);
    return [latSum / allLocations.length, lngSum / allLocations.length] as [number, number];
  }, [allLocations]);

  const zoom = useMemo(() => {
    return allLocations.length > 0 ? 12 : 5;
  }, [allLocations]);

  const [activeDay, setActiveDay] = useState(0);
  const [animateRoute, setAnimateRoute] = useState(false);
  const [selectedLocation, setSelectedLocation] = useState<Location | null>(null);
  const [expandedPopup, setExpandedPopup] = useState<number | null>(null);

  const activeLocations = useMemo(() => {
    return itinerary[activeDay]?.locations || [];
  }, [itinerary, activeDay]);

  const route = useMemo(() => {
    return activeLocations.map(loc => [loc.lat, loc.lng] as [number, number]);
  }, [activeLocations]);

  // 为地点添加图片和额外信息
  const enhancedLocations = useMemo(() => {
    return activeLocations.map(location => {
      // 查找对应的图片
      let imageUrl = '';
      for (const [key, url] of Object.entries(locationImages)) {
        if (location.name.includes(key) || location.description?.includes(key)) {
          imageUrl = url;
          break;
        }
      }

      // 查找对应的标签
      let tags: string[] = [];
      for (const [key, tagList] of Object.entries(locationTags)) {
        if (location.name.includes(key) || location.description?.includes(key)) {
          tags = tagList;
          break;
        }
      }

      return {
        ...location,
        imageUrl,
        rating: 4.5 + Math.random() * 0.5, // 模拟评分
        duration: `${Math.floor(Math.random() * 3) + 1}-${Math.floor(Math.random() * 2) + 2}小时`, // 模拟游览时长
        tags,
        address: `中国, ${location.name}附近` // 模拟地址
      };
    });
  }, [activeLocations]);

  // 检查是否在客户端
  const isClient = typeof window !== 'undefined';

  // 路线动画效果
  useEffect(() => {
    if (activeLocations.length > 1) {
      setAnimateRoute(true);
      const timer = setTimeout(() => setAnimateRoute(false), 3000);
      return () => clearTimeout(timer);
    }
  }, [activeDay]);

  // 模拟路线点动画
  const animatedRoute = useMemo(() => {
    if (!animateRoute || route.length < 2) return route;
    
    const progress = 0.5; // 可以根据时间动态计算
    const points: [number, number][] = [];
    for (let i = 0; i < route.length - 1; i++) {
      const start = route[i];
      const end = route[i + 1];
      const x = start[0] + (end[0] - start[0]) * progress;
      const y = start[1] + (end[1] - start[1]) * progress;
      points.push(start);
      if (i === route.length - 2) {
        points.push([x, y] as [number, number]);
      }
    }
    return points;
  }, [route, animateRoute]);

  return (
    <div className={`rounded-xl md:rounded-2xl border border-border/70 bg-white dark:bg-slate-950 shadow-soft overflow-hidden ${className}`}>
      <div className="p-3 md:p-4 border-b border-border/70">
        <div className="flex items-center justify-between mb-2 md:mb-3">
          <div className="flex items-center gap-2">
            <Map className="h-4 w-4 md:h-5 md:w-5 text-sky-600 dark:text-sky-400" />
            <h3 className="text-base md:text-lg font-semibold text-slate-900 dark:text-slate-50">行程地图</h3>
          </div>
          <div className="flex items-center gap-2">
            {activeLocations.length > 1 && (
              <button
                onClick={() => setAnimateRoute(true)}
                className="flex items-center gap-1 md:gap-2 px-2 py-1 rounded-full text-xs font-medium bg-sky-100 text-sky-700 dark:bg-sky-950/30 dark:text-sky-300 hover:bg-sky-200 dark:hover:bg-sky-950/50 transition-colors"
              >
                <Navigation className="h-3 w-3" />
                <span className="hidden sm:inline">路线动画</span>
              </button>
            )}
            {selectedLocation && (
              <button
                onClick={() => setSelectedLocation(null)}
                className="flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
              >
                <MapPin className="h-3 w-3" />
                <span className="hidden sm:inline">清除选择</span>
              </button>
            )}
          </div>
        </div>
        <div className="flex gap-1 md:gap-2 overflow-x-auto pb-1 md:pb-2">
          {itinerary.map((day, index) => (
            <button
              key={day.day}
              onClick={() => {
                setActiveDay(index);
                setSelectedLocation(null);
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
      </div>
      
      {/* 地点信息卡片 */}
      {selectedLocation && (
        <div className="p-3 md:p-4 border-b border-border/70 bg-slate-50/50 dark:bg-slate-900/50">
          <div className="flex items-start gap-3">
            {selectedLocation.imageUrl && (
              <div className="w-16 h-16 rounded-lg overflow-hidden flex-shrink-0">
                <img 
                  src={selectedLocation.imageUrl} 
                  alt={selectedLocation.name} 
                  className="w-full h-full object-cover"
                />
              </div>
            )}
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h4 className="font-semibold text-slate-900 dark:text-slate-50">{selectedLocation.name}</h4>
                {selectedLocation.rating && (
                  <div className="flex items-center gap-1">
                    <Star className="h-3 w-3 text-amber-500 fill-amber-500" />
                    <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{selectedLocation.rating.toFixed(1)}</span>
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2 mt-1 text-xs text-slate-600 dark:text-slate-300">
                <Clock3 className="h-3 w-3" />
                <span>建议游览：{selectedLocation.duration}</span>
              </div>
              {selectedLocation.tags && selectedLocation.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {selectedLocation.tags.map((tag, index) => (
                    <span key={index} className="px-2 py-0.5 rounded-full text-xs bg-sky-100 text-sky-700 dark:bg-sky-950/30 dark:text-sky-300">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      
      <div className="h-[250px] sm:h-[300px] md:h-[350px] lg:h-[400px]">
        {isClient ? (
          <React.Suspense fallback={<div className="h-full flex items-center justify-center text-slate-500">加载地图中...</div>}>
            <MapContainer center={center} zoom={zoom} style={{ height: '100%', width: '100%' }}>
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              
              {/* 主路线 */}
              {route.length > 1 && (
                <Polyline
                  positions={route}
                  pathOptions={{
                    color: '#3b82f6',
                    weight: 3,
                    opacity: 0.7,
                    dashArray: animateRoute ? '5, 10' : '0'
                  }}
                />
              )}
              
              {/* 动画路线 */}
              {animateRoute && route.length > 1 && (
                <Polyline
                  positions={animatedRoute}
                  pathOptions={{
                    color: '#ef4444',
                    weight: 4,
                    opacity: 0.9,
                    dashArray: '5, 5'
                  }}
                />
              )}
              
              {enhancedLocations.map((location, index) => (
                <Marker 
                  key={index} 
                  position={[location.lat, location.lng]}
                  eventHandlers={{
                    click: () => setSelectedLocation(location)
                  }}
                >
                  <Tooltip direction="top" offset={[0, -15]}>
                    <div className="text-xs font-medium">{location.name}</div>
                  </Tooltip>
                  <Popup maxWidth={300}>
                    <div className="p-2">
                      <div className="flex items-center justify-between mb-2">
                        <h4 className="font-semibold text-slate-900 dark:text-slate-50">{location.name}</h4>
                        <button
                          onClick={() => setExpandedPopup(expandedPopup === index ? null : index)}
                          className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                        >
                          <ChevronDown className={`h-4 w-4 transition-transform ${expandedPopup === index ? 'rotate-180' : ''}`} />
                        </button>
                      </div>
                      
                      {/* 地点图片 */}
                      {location.imageUrl && (
                        <div className="mb-3 rounded-lg overflow-hidden">
                          <img 
                            src={location.imageUrl} 
                            alt={location.name} 
                            className="w-full h-32 object-cover"
                          />
                        </div>
                      )}
                      
                      {/* 基本信息 */}
                      <div className="space-y-1 mb-2">
                        {location.time && (
                          <div className="flex items-center gap-1 text-xs md:text-sm text-slate-600 dark:text-slate-300">
                            <Clock className="h-3 w-3" />
                            <span>{location.time}</span>
                          </div>
                        )}
                        
                        {location.duration && (
                          <div className="flex items-center gap-1 text-xs md:text-sm text-slate-600 dark:text-slate-300">
                            <Info className="h-3 w-3" />
                            <span>建议游览：{location.duration}</span>
                          </div>
                        )}
                        
                        {location.rating && (
                          <div className="flex items-center gap-1 text-xs md:text-sm">
                            <div className="text-amber-500">★★★★★</div>
                            <span className="text-slate-600 dark:text-slate-300">{location.rating.toFixed(1)}</span>
                          </div>
                        )}
                        
                        {location.address && (
                          <div className="flex items-center gap-1 text-xs md:text-sm text-slate-600 dark:text-slate-300">
                            <MapPin className="h-3 w-3" />
                            <span>{location.address}</span>
                          </div>
                        )}
                      </div>
                      
                      {/* 展开信息 */}
                      {expandedPopup === index && (
                        <div className="mt-2 pt-2 border-t border-slate-200 dark:border-slate-700">
                          {/* 标签 */}
                          {location.tags && location.tags.length > 0 && (
                            <div className="flex flex-wrap gap-1 mb-2">
                              {location.tags.map((tag, tagIndex) => (
                                <span key={tagIndex} className="px-2 py-0.5 rounded-full text-xs bg-sky-100 text-sky-700 dark:bg-sky-950/30 dark:text-sky-300">
                                  {tag}
                                </span>
                              ))}
                            </div>
                          )}
                          
                          {/* 地点描述 */}
                          {location.description && (
                            <p className="text-xs md:text-sm text-slate-700 dark:text-slate-200">{location.description}</p>
                          )}
                        </div>
                      )}
                    </div>
                  </Popup>
                </Marker>
              ))}
            </MapContainer>
          </React.Suspense>
        ) : (
          <div className="h-full flex items-center justify-center text-slate-500">地图加载中...</div>
        )}
      </div>
    </div>
  );
}

export { MapView };