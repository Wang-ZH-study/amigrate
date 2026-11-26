;; pilot3_paramset.il — 诊断：n12 pcell 实例的 w/l 到底怎么才能写进去
;; 用法：cd /home/IC && timeout 240 virtuoso -nograph < /tmp/pilot3_paramset.il

(printf "\n=== PILOT3 START\n")
(unless (ddGetObj "port_pilot")
  (ddCreateLib "port_pilot" "/home/IC/port_pilot"))
(when (ddGetObj "port_pilot" "pilot_n12")
  (ddDeleteObj (ddGetObj "port_pilot" "pilot_n12")))

(let (cv inst)
  (setq cv (dbOpenCellViewByType "port_pilot" "pilot_n12" "schematic" "schematic" "w"))
  (setq inst (dbCreateInstByMasterName cv "smic13mmrf_1233" "n12" "symbol" "M1" 0:0 "R0"))
  (printf "init: master=%s/%s\n" inst~>master~>libName inst~>master~>cellName)
  (printf "init: w=%L l=%L fingers=%L m=%L\n" inst~>w inst~>l inst~>fingers inst~>m)

  ;; A) 带单位后缀的字符串
  (dbSet inst "w" "2u")
  (dbSet inst "l" "500n")
  (printf "A dbSet 2u/500n: dbGet w=%L  inst~>w=%L  dbGet l=%L inst~>l=%L\n"
          (dbGet inst "w") inst~>w (dbGet inst "l") inst~>l)

  ;; B) dbReplaceProp
  (dbReplaceProp inst "w" "3u" 'string)
  (printf "B dbReplaceProp w=3u: dbGet w=%L inst~>w=%L\n" (dbGet inst "w") inst~>w)

  ;; C) 数字形式（预期报类型错，验证可行）
  (errset (dbSet inst "l" 0.6e-6))
  (printf "C dbSet numeric l=0.6e-6: dbGet l=%L inst~>l=%L\n" (dbGet inst "l") inst~>l)

  ;; D) 直接写 instance 属性字符串（带单位）
  (dbSet inst "w" "4u")
  (printf "D w=4u: dbGet w=%L inst~>w=%L fingers=%L\n" (dbGet inst "w") inst~>w inst~>fingers)

  (schCheck cv)
  (dbSave cv)
  (dbClose cv))

;; 重新打开验证
(let (cv inst)
  (setq cv (dbOpenCellViewByType "port_pilot" "pilot_n12" "schematic" "schematic" "r"))
  (setq inst (car cv~>instances))
  (printf "reopen: w=%L l=%L fingers=%L m=%L\n" inst~>w inst~>l inst~>fingers inst~>m)
  (dbClose cv))

(printf "=== PILOT3 DONE\n")
(exit)