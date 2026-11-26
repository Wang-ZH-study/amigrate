;; pilot4_params.il — 诊断：n12 是不是 pcell？哪些参数可写？
(printf "\n=== PILOT4 START\n")
(unless (ddGetObj "port_pilot")
  (ddCreateLib "port_pilot" "/home/IC/port_pilot"))
(when (ddGetObj "port_pilot" "pilot_n12")
  (ddDeleteObj (ddGetObj "port_pilot" "pilot_n12")))

(let (cv inst)
  (setq cv (dbOpenCellViewByType "port_pilot" "pilot_n12" "schematic" "schematic" "w"))
  (setq inst (dbCreateInstByMasterName cv "smic13mmrf_1233" "n12" "symbol" "M1" 0:0 "R0"))
  (printf "debug: isParamCell=%L superMaster=%L view=%L\n"
          inst~>master~>isParamCell inst~>master~>superMaster inst~>master~>viewName)
  (printf "props: w=%L l=%L fw=%L simW=%L fingers=%L m=%L\n"
          (dbGet inst "w") (dbGet inst "l") (dbGet inst "fw")
          (dbGet inst "simW") (dbGet inst "fingers") (dbGet inst "m"))
  ;; 试写 fw / simW / fingers
  (dbSet inst "fw" "2u")
  (dbSet inst "simW" "2u")
  (dbSet inst "fingers" "2")
  (printf "after: fw=%L simW=%L fingers=%L w=%L l=%L\n"
          (dbGet inst "fw") (dbGet inst "simW") (dbGet inst "fingers")
          (dbGet inst "w") (dbGet inst "l"))
  ;; 列出实例上所有属性名（前 40 个）
  (printf "inst prop names: %L\n" (mapcar 'car (dbGetq inst "prop")))
  (schCheck cv)
  (dbSave cv)
  (dbClose cv))

(printf "=== PILOT4 DONE\n")
(exit)